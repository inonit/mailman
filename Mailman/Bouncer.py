# Copyright (C) 1998,1999,2000,2001 by the Free Software Foundation, Inc.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software 
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

"""Handle delivery bounces.
"""

import sys
import time

from email.MIMEText import MIMEText
from email.MIMEMessage import MIMEMessage

from Mailman import mm_cfg
from Mailman import Utils
from Mailman import Message
from Mailman import MemberAdaptor
from Mailman import Pending
from Mailman.Logging.Syslog import syslog
from Mailman.i18n import _

EMPTYSTRING = ''

class _BounceInfo:
    def __init__(self, member, score, date, noticesleft, cookie):
        self.member = member
        self.score = score
        self.date = date
        self.noticesleft = noticesleft
        self.lastnotice = None
        self.cookie = cookie

    def __repr__(self):
        # For debugging
        return """\
<bounce info for member %(member)s
        current score: %(score)s
        last bounce date: %(date)s
        email notices left: %(noticesleft)s
        last notice date: %(lastnotice)s
        confirmation cookie: %(cookie)s
        >""" % self.__dict__



class Bouncer:
    def InitVars(self):
        # Configurable...
        self.bounce_processing = mm_cfg.DEFAULT_BOUNCE_PROCESSING
        self.bounce_score_threshold = mm_cfg.DEFAULT_BOUNCE_SCORE_THRESHOLD
        self.bounce_info_stale_after = mm_cfg.DEFAULT_BOUNCE_INFO_STALE_AFTER
        self.bounce_you_are_disabled_warnings = \
            mm_cfg.DEFAULT_BOUNCE_YOU_ARE_DISABLED_WARNINGS
        self.bounce_you_are_disabled_warnings_interval = \
            mm_cfg.DEFAULT_BOUNCE_YOU_ARE_DISABLED_WARNINGS_INTERVAL
        # Not configurable...
        #
        # This holds legacy member related information.  It's keyed by the
        # member address, and the value is an object containing the bounce
        # score, the date of the last received bounce, and a count of the
        # notifications left to send.
        self.bounce_info = {}
        # New style delivery status
        self.delivery_status = {}

    def registerBounce(self, member, msg, weight=1.0):
        if not self.isMember(member):
            return
        info = self.getBounceInfo(member)
        today = time.localtime()[:3]
        if info is None:
            # This is the first bounce we've seen from this member
            cookie = Pending.new(Pending.RE_ENABLE, self.internal_name(),
                                 member)
            info = _BounceInfo(member, weight, today,
                               self.bounce_you_are_disabled_warnings,
                               cookie)
            self.setBounceInfo(member, info)
            syslog('bounce', '%s: %s bounce score: %s', self.internal_name(),
                   member, info.score)
        elif self.getDeliveryStatus(member) <> MemberAdaptor.ENABLED:
            # The user is already disabled, so we can just ignore subsequent
            # bounces.  These are likely due to residual messages that were
            # sent before disabling the member, but took a while to bounce.
            syslog('bounce', '%s: %s residual bounce received',
                   self.internal_name(), member)
        elif info.date == today:
            # We've already scored any bounces for today, so ignore this one.
            syslog('bounce', '%s: %s already scored a bounce for today',
                   self.internal_name(), member)
        else:
            # See if this member's bounce information is stale.
            now = time.mktime(today + (0,) * 6)
            lastbounce = time.mktime(info.date + (0,) * 6)
            if lastbounce + self.bounce_info_stale_after < now:
                # Information is stale, so simply reset it
                info = _BounceInfo(member, weight, today, 0)
                self.setBounceInfo(member, info)
                syslog('bounce', '%s: %s has stale bounce info, resetting',
                       self.internal_name(), member)
            else:
                # Nope, the information isn't stale, so add to the bounce
                # score and take any necessary action.
                info.score += weight
                info.date = today
                self.setBounceInfo(member, info)
                syslog('bounce', '%s: %s current bounce score: %s',
                       member, self.internal_name(), info.score)
                if info.score >= self.bounce_score_threshold:
                    # Disable them
                    syslog('bounce',
                           '%s: %s disabling due to bounce score %s >= %s',
                           self.internal_name(), member,
                           info.score, self.bounce_score_threshold)
                    self.setDeliveryStatus(member, MemberAdaptor.BYBOUNCE)
                    self.sendNextNotification(member)
                    self.__sendAdminBounceNotice(member, msg)

    def __sendAdminBounceNotice(self, member, msg):
        # BAW: This is a bit kludgey, but we're not providing as much
        # information in the new admin bounce notices as we used to (some of
        # it was of dubious value).  However, we'll provide empty, strange, or
        # meaningless strings for the unused %()s fields so that the language
        # translators don't have to provide new templates.
        siteowner = Utils.get_site_email(self.host_name)
        text = Utils.maketext(
            'bounce.txt',
            {'listname' : self.real_name,
             'addr'     : member,
             'negative' : '',
             'did'      : _('disabled'),
             'but'      : '',
             'reenable' : '',
             'owneraddr': siteowner,
             }, mlist=self)
        subject = _('Bounce action notification')
        umsg = Message.UserNotification(self.GetOwnerEmail(),
                                        siteowner, subject)
        umsg.attach(MIMEText(text))
        umsg.attach(MIMEMessage(msg))
        umsg['Content-Type'] = 'multipart/mixed'
        umsg['MIME-Version'] = '1.0'
        umsg.send(self)

    def sendNextNotification(self, member):
        info = self.getBounceInfo(member)
        if info is None:
            return
        if info.noticesleft <= 0:
            # BAW: Remove them now, with a notification message
            self.ApprovedDeleteMember(member, 'bouncing address',
                                      admin_notif=1, userack=1)
            self.setBounceInfo(member, None)
            # Expunge the pending cookie for the user.  We throw away the
            # returned data.
            Pending.confirm(info.cookie)
            syslog('bounce', '%s: %s deleted after exhausting notices',
                   self.internal_name(), member)
            return
        # Send the next notification
        confirmurl = '%s/%s' % (self.GetScriptURL('confirm', absolute=1),
                                info.cookie)
        optionsurl = self.GetOptionsURL(member, absolute=1)
        subject = 'confirm ' + info.cookie
        requestaddr = self.GetRequestEmail()
        text = Utils.maketext(
            'disabled.txt',
            {'listname'   : self.real_name,
             'noticesleft': info.noticesleft,
             'confirmurl' : confirmurl,
             'optionsurl' : optionsurl,
             'password'   : self.getMemberPassword(member),
             'owneraddr'  : self.GetOwnerEmail(),
             }, lang=self.getMemberLanguage(member), mlist=self)
        msg = Message.UserNotification(member, requestaddr, subject, text)
        msg.send(self)
        info.noticesleft -= 1
        info.lastnotice = time.localtime()[:3]

    def BounceMessage(self, msg, msgdata, e=None):
        # Bounce a message back to the sender, with an error message if
        # provided in the exception argument.
        sender = msg.get_sender()
        subject = msg.get('subject', _('(no subject)'))
        if e is None:
            notice = _('[No bounce details are available]')
        else:
            notice = _(e.notice())
        # Currently we always craft bounces as MIME messages.
        bmsg = Message.UserNotification(msg.get_sender(),
                                        self.GetOwnerEmail(),
                                        subject)
        bmsg['Content-Type'] = 'multipart/mixed'
        bmsg['MIME-Version'] = '1.0'
        txt = MIMEText(notice,
                       _charset=Utils.GetCharSet(self.preferred_language))
        bmsg.add_payload(txt)
        bmsg.add_payload(MIMEMessage(msg))
        bmsg.send(self)
