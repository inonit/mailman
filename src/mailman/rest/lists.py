# Copyright (C) 2010 by the Free Software Foundation, Inc.
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

"""REST for mailing lists."""

from __future__ import absolute_import, unicode_literals

__metaclass__ = type
__all__ = [
    'AList',
    'AllLists',
    ]


from restish import http, resource
from zope.component import getUtility

from mailman.app.lifecycle import create_list
from mailman.interfaces.domain import BadDomainSpecificationError
from mailman.interfaces.listmanager import (
    IListManager, ListAlreadyExistsError)
from mailman.interfaces.member import MemberRole
from mailman.rest.helpers import (
    CollectionMixin, Validator, etag, path_to, restish_matcher)
from mailman.rest.members import AMember, MembersOfList



@restish_matcher
def member_matcher(request, segments):
    """A matcher of member URLs inside mailing lists.

    e.g. /member/aperson@example.org
    """
    if len(segments) != 2:
        return None
    try:
        role = MemberRole[segments[0]]
    except ValueError:
        # Not a valid role.
        return None
    # No more segments.
    # XXX 2010-02-25 barry Matchers are undocumented in restish; they return a
    # 3-tuple of (match_args, match_kws, segments).
    return (), dict(role=role, address=segments[1]), ()


@restish_matcher
def roster_matcher(request, segments):
    """A matcher of all members URLs inside mailing lists.

    e.g. /roster/members
         /roster/owners
         /roster/moderators

    The URL roles are the plural form of the MemberRole enum, because the
    former reads better.
    """
    if len(segments) != 2 or segments[0] != 'roster':
        return None
    role = segments[1][:-1]
    try:
        return (), dict(role=MemberRole[role]), ()
    except ValueError:
        # Not a valid role.
        return None



class _ListBase(resource.Resource, CollectionMixin):
    """Shared base class for mailing list representations."""

    def _resource_as_dict(self, mlist):
        """See `CollectionMixin`."""
        return dict(
            fqdn_listname=mlist.fqdn_listname,
            host_name=mlist.host_name,
            list_name=mlist.list_name,
            real_name=mlist.real_name,
            self_link=path_to('lists/{0}'.format(mlist.fqdn_listname)),
            )

    def _get_collection(self, request):
        """See `CollectionMixin`."""
        return list(getUtility(IListManager))


class AList(_ListBase):
    """A mailing list."""

    def __init__(self, list_name):
        self._mlist = getUtility(IListManager).get(list_name)

    @resource.GET()
    def mailing_list(self, request):
        """Return a single mailing list end-point."""
        if self._mlist is None:
            return http.not_found()
        return http.ok([], self._resource_as_json(self._mlist))

    @resource.child(member_matcher)
    def member(self, request, segments, role, address):
        """Return a single member representation."""
        return AMember(self._mlist, role, address)

    @resource.child(roster_matcher)
    def roster(self, request, segments, role):
        """Return the collection of all a mailing list's members."""
        return MembersOfList(self._mlist, role)


class AllLists(_ListBase):
    """The mailing lists."""

    @resource.POST()
    def create(self, request):
        """Create a new mailing list."""
        try:
            validator = Validator(fqdn_listname=unicode)
            mlist = create_list(**validator(request))
        except ListAlreadyExistsError:
            return http.bad_request([], b'Mailing list exists')
        except BadDomainSpecificationError as error:
            return http.bad_request([], b'Domain does not exist {0}'.format(
                error.domain))
        except ValueError as error:
            return http.bad_request([], str(error))
        # wsgiref wants headers to be bytes, not unicodes.
        location = path_to('lists/{0}'.format(mlist.fqdn_listname))
        # Include no extra headers or body.
        return http.created(location, [], None)

    @resource.GET()
    def collection(self, request):
        """/lists"""
        resource = self._make_collection(request)
        return http.ok([], etag(resource))