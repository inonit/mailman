# Copyright (C) 2015 by the Free Software Foundation, Inc.
#
# This file is part of GNU Mailman.
#
# GNU Mailman is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.
#
# GNU Mailman is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.
#
# You should have received a copy of the GNU General Public License along with
# GNU Mailman.  If not, see <http://www.gnu.org/licenses/>.

"""Test pendings."""

__all__ = [
    'TestPendings',
    ]


import unittest

from mailman.config import config
from mailman.email.validate import InvalidEmailAddressError
from mailman.interfaces.pending import (
    IPendable, IPended, IPendedKeyValue, IPendings)
from mailman.model.pending import PendedKeyValue, Pended, Pendings
from mailman.testing.layers import ConfigLayer
from zope.component import getUtility
from zope.interface import implementer


@implementer(IPendable)
class SimplePendable(dict):
    pass



class TestPendings(unittest.TestCase):
    """Test pendings."""

    layer = ConfigLayer

    def test_delete_key_values(self):
        # Deleting a pending should delete its key-values
        pendingdb = getUtility(IPendings)
        subscription = SimplePendable(
            type='subscription',
            address='aperson@example.com',
            display_name='Anne Person',
            language='en',
            password='xyz')
        token = pendingdb.add(subscription)
        self.assertEqual(pendingdb.count, 1)
        pendable = pendingdb.confirm(token)
        self.assertEqual(pendingdb.count, 0)
        self.assertEqual(config.db.store.query(PendedKeyValue).count(), 0)
