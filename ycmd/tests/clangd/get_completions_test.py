# encoding: utf-8
#
# Copyright (C) 2015 ycmd contributors
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

from __future__ import absolute_import
from __future__ import unicode_literals
from __future__ import print_function
from __future__ import division
# Not installing aliases from python-future; it's unreliable and slow.
from builtins import *  # noqa

from hamcrest import ( assert_that, contains_inanyorder, has_entries )

from ycmd.tests.clangd import PathToTestFile, SharedYcmd
from ycmd.tests.test_utils import ( BuildRequest, CompletionEntryMatcher )
from ycmd.utils import ReadFile


def RunTest( app, test ):
  filepath = PathToTestFile( 'test.cpp' )
  contents = ReadFile( filepath )

  event_data = BuildRequest( filepath = filepath,
                             filetype = 'cpp',
                             contents = contents,
                             event_name = 'BufferVisit' )

  app.post_json( '/event_notification', event_data )

  completion_data = BuildRequest( filepath = filepath,
                                  filetype = 'cpp',
                                  contents = contents,
                                  force_semantic = True,
                                  line_num = 7,
                                  column_num = 5 )

  response = app.post_json( '/completions', completion_data )

  print( response )

  assert_that( response.json, test[ 'expect' ][ 'data' ] )


@SharedYcmd
def GetCompletions_Basic_test( app ):
  RunTest( app, {
    'expect': {
      'data': has_entries( {
        'completions': contains_inanyorder(
          CompletionEntryMatcher( 'x' ),
          CompletionEntryMatcher( 'yy' ),
          CompletionEntryMatcher( '~S' ),
          CompletionEntryMatcher( 'operator=' ),
          CompletionEntryMatcher( 'S' ),
        )
      } )
    }
  } )
