# Copyright (C) 2011-2012 Google Inc.
#               2017      ycmd contributors
#
# This file is part of ycmd.
#
# ycmd is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# ycmd is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with ycmd.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import unicode_literals
from __future__ import print_function
from __future__ import division
from __future__ import absolute_import
# Not installing aliases from python-future; it's unreliable and slow.
from builtins import *  # noqa

try:
  # For Python 3.3
  from collections import OrderedDict
except ImportError:
  # For Python 2.6
  from ordereddict import OrderedDict

import subprocess
import threading
import itertools
import json
import logging

import ycm_core
from ycmd import responses, utils
from ycmd.completers.completer import Completer

PATH_TO_CLANGD = utils.FindExecutable('/usr/bin/clangdtee.sh')
CLANG_FILETYPES = set( [ 'c', 'cpp', 'objc', 'objcpp' ] )

SERVER_NOT_RUNNING_MESSAGE = 'clangd is not running'
RESPONSE_TIMEOUT_SECONDS = 10

_logger = logging.getLogger( __name__ )


def ShouldEnableClangdCompleter():
  if ycm_core.HasClangSupport():
    return False
  if not PATH_TO_CLANGD:
    _logger.warning( 'Not using clangd: unable to find clangd binary' )
    return False
  _logger.info( 'Using clangd from {0}'.format( PATH_TO_CLANGD ) )
  return True


class DeferredResponse( object ):
  """
  A deferred that resolves to a response from clangd.
  """


  def __init__( self, timeout = RESPONSE_TIMEOUT_SECONDS ):
    self._event = threading.Event()
    self._message = None
    self._timeout = timeout


  def resolve( self, message ):
    self._message = message
    self._event.set()


  def result( self ):
    self._event.wait( timeout = self._timeout )
    if not self._event.isSet():
      raise RuntimeError( 'Response Timeout' )
    return self._message


class ClangdCompleter( Completer ):
  """
  Completer for C-family languages based on clangd, which is in turn speaking
  the Language Server Protocol.

  See:
  https://github.com/llvm-mirror/clang-tools-extra/tree/master/clangd
  https://github.com/Microsoft/language-server-protocol
  """


  def __init__( self, user_options ):
    super( ClangdCompleter, self ).__init__( user_options )

    # Used to hold a handle to the running clangd server process.
    self._server = None
    self._server_is_running = threading.Event()

    # Used to generate a unique id for requests to the server.
    self._sequenceid = itertools.count()
    self._sequenceid_lock = threading.Lock()

    # Used to map sequence id's to their corresponding DeferredResponses.
    # The reader loop uses this to hand out responses.
    self._pending = {}
    self._pending_lock = threading.Lock()

    self._diagnostics = None
    self._diagnostics_lock = threading.Lock()
    self._has_diagnostics = threading.Event()

    # Used to hold the thread that runs the reader loop that reads responses
    # from the server.
    self._reader_thread = threading.Thread( target = self._ReaderLoop )
    self._reader_thread.daemon = True
    self._reader_thread.start()

    self._StartServer()


  def _BuildRequest( self, method, params, use_sequenceid = True ):
    """
    Build a Language Server Protocol request.
    """
    request = OrderedDict()
    request[ 'jsonrpc' ] = '2.0'
    if use_sequenceid:
      with self._sequenceid_lock:
        request[ 'id' ] = next( self._sequenceid )
    request[ 'method' ] = method
    if params is not None:
      request[ 'params' ] = params
    return request


  def _Write( self, request ):
    """
    Write a request to clangd.
    """
    request_json = json.dumps( request, separators = ( ',', ':' ) )
    request_serialized = utils.ToBytes(
      'Content-Length: %d\r\n\r\n%s' % ( len( request_json ), request_json ) )
    print( 'Writing:\n', request_serialized )
    self._server.stdin.write( request_serialized )
    self._server.stdin.flush()


  def _Read( self ):
    """
    Read a message from clangd.
    """

    headers = {}
    while True:
      headerline = self._server.stdout.readline().strip()
      print( 'headerline: ', headerline )
      if not headerline:
        break
      key, value = utils.ToUnicode( headerline ).split( ':', 1 )
      headers[ key.strip() ] = value.strip()

    if 'Content-Length' not in headers:
      raise RuntimeError( "Missing 'Content-Length' header" )
    contentlength = int( headers[ 'Content-Length' ] )
    content = self._server.stdout.read( contentlength )
    return json.loads( utils. ToUnicode( content ) )


  def _ReaderLoop( self ):
    """
    Read responses from clangd and use them to resolve the DeferredResponse
    instances.
    """

    while True:
      self._server_is_running.wait()

      try:
        message = self._Read()
      except:
        _logger.exception( SERVER_NOT_RUNNING_MESSAGE )
        self._server_is_running.clear()
        continue

      if 'id' in message:
        sequenceid = message[ 'id' ]
        with self._pending_lock:
          if sequenceid in self._pending:
            self._pending[ sequenceid ].resolve( message )
            del self._pending[ sequenceid ]
      else:
        method = message[ 'method' ]
        print( method, message )
        if method == 'textDocument/publishDiagnostics':
          with self._diagnostics_lock:
            self._diagnostics = message
            self._has_diagnostics.set()


  def _Notify( self, method, params ):
    """
    Sends a notification to clangd.
    """
    request = self._BuildRequest( method, params, use_sequenceid = False )
    self._Write( request )


  def _SendRequest( self, request ):
    """
    Sends a request to clangd and waits for the response.
    """
    deferred = DeferredResponse()
    with self._pending_lock:
      sequenceid = request[ 'id' ]
      self._pending[ sequenceid ] = deferred
    self._Write( request )
    return deferred.result()


  def _Invoke( self, method, params ):
    """
    Invokes a Language Server Protocol method with the given params and returns
    the response.
    """
    request = self._BuildRequest( method, params )
    return self._SendRequest( request )


  def _StartServer( self, capabilities = {} ):
    print( 'Starting server: {0}'.format( PATH_TO_CLANGD ) )
    self._server = subprocess.Popen( PATH_TO_CLANGD,
                                     stdin = subprocess.PIPE,
                                     stdout = subprocess.PIPE,
                                     stderr = subprocess.PIPE )
    self._server_is_running.set()
    return self._Invoke( method = 'initialize',
                         params = { 'capabilities' : capabilities } )


  def SupportedFiletypes( self ):
    return CLANG_FILETYPES


  def OnBufferVisit( self, request_data ):
    filename = request_data[ 'filepath' ]
    contents = request_data[ 'file_data' ][ filename ][ 'contents' ]
    print( 'OnBufferVisit: ', filename )
    self._Notify(
      method = 'textDocument/didOpen',
      params = {
        'textDocument': {
          'uri': filename,
          'languageId': 'cpp',
          'version': 1,
          'text': contents
        }
      } )


  def OnFileReadyToParse( self, request_data ):
    filename = request_data[ 'filepath' ]
    contents = request_data[ 'file_data' ][ filename ][ 'contents' ]
    print( 'OnFileReadyToParse: ', filename )
    self._Notify(
      method = 'textDocument/didOpen',
      params = {
        'textDocument': {
          'uri': filename,
          'languageId': 'cpp',
          'version': 1,
          'text': contents
        }
      })
    return self.GetDiagnosticsForCurrentFile( request_data )


  def _LSPCompletionItemToCompletionData(self, data):
    return responses.BuildCompletionData(
      insertion_text = data[ 'label' ],
      kind = data.get( 'kind', None )
    )


  def ComputeCandidatesInner( self, request_data ):
    filename = request_data[ 'filepath' ]
    line = request_data[ 'line_num' ]
    offset = request_data[ 'start_codepoint' ]
    res = self._Invoke(
      method = 'textDocument/completion',
      params = {
        'textDocument': { 'uri': filename },
        'position': {
          'line': line - 1, # LSP lines are zero-based.
          'character': offset
        }
      })
    return [ self._LSPCompletionItemToCompletionData( data )
             for data in res[ 'result' ] ]


  def _LspToYcmdDiagnostic( self, filepath, line_value, lsp_diagnostic ):
    lsp_range_start = lsp_diagnostic[ 'range' ][ 'start' ]
    lsp_range_end = lsp_diagnostic[ 'range' ][ 'end' ]

    start_offset = utils.CodepointOffsetToByteOffset(
                     line_value,
                     lsp_range_start[ 'character' ] )
    end_offset = utils.CodepointOffsetToByteOffset(
                   line_value,
                   lsp_range_end[ 'character' ] )

    location_start = responses.Location( lsp_range_start[ 'line' ],
                                         start_offset,
                                         filepath )
    location_end = responses.Location( lsp_range_end[ 'line' ],
                                       end_offset,
                                       filepath )

    location_extent = responses.Range( location_start, location_end )

    return responses.Diagnostic( [ location_extent ],
                                 location_start,
                                 location_extent,
                                 lsp_diagnostic[ 'message' ],
                                 'ERROR' )


  def GetDiagnosticsForCurrentFile( self, request_data ):
    filepath = request_data[ 'filepath' ]
    line_value = request_data[ 'line_value' ]
    print( 'filepath', filepath )
    self._has_diagnostics.wait()
    with self._diagnostics_lock:
      diagnostics = self._diagnostics
      self._diagnostics = None
      self._has_diagnostics.clear()
    res = [ self._LspToYcmdDiagnostic( filepath, line_value, lsp_diagnostic)
           for lsp_diagnostic in diagnostics[ 'params' ][ 'diagnostics' ] ]
    print( res )
    return res
