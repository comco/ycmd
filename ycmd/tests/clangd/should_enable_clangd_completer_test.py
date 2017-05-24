# Copyright (C) 2017 ycmd contributors
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

from mock import patch
from nose.tools import ok_

from ycmd.completers.clangd.clangd_completer import (
    ShouldEnableClangdCompleter )


@patch( 'ycmd.completers.clangd.clangd_completer.USE_CLANGD_INSTEAD_OF_CLANG',
        True )
def ShouldEnableClangdCompleter_UseClangdFound_test():
  ok_( ShouldEnableClangdCompleter() )


@patch( 'ycmd.completers.clangd.clangd_completer.USE_CLANGD_INSTEAD_OF_CLANG',
        True )
@patch( 'ycmd.completers.clangd.clangd_completer.PATH_TO_CLANGD', None )
def ShouldEnableClangdCompleter_UseClangdNotFound_test():
  ok_( not ShouldEnableClangdCompleter() )


@patch( 'ycmd.completers.clangd.clangd_completer.USE_CLANGD_INSTEAD_OF_CLANG',
        False )
@patch( 'ycm_core.HasClangSupport', lambda : True )
def ShouldEnableClangdCompleter_NotUseClangdAndHasClangSupport_test():
  ok_( not ShouldEnableClangdCompleter() )
