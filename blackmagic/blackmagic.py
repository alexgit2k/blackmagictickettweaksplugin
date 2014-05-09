# -*- coding: utf-8 -*-
#
# Copyright (C) 2008 Stephen Hansen <shansen@advpubtech.com>
# Copyright (C) 2009 Rowan Wookey <support@obsidianproject.co.uk>
# Copyright (C) 2008-2009 www.obsidianproject.co.uk
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

from genshi.builder import tag
from genshi.core import Markup
from genshi.filters.transform import Transformer
from genshi.filters.transform import StreamBuffer
from trac.config import ListOption, Option
from trac.core import Component, TracError, implements
from trac.perm import IPermissionPolicy, IPermissionRequestor, IPermissionStore
from trac.ticket import model
from trac.ticket.model import Ticket
from trac.ticket.api import ITicketManipulator
from trac.web.api import IRequestFilter, ITemplateStreamFilter
from trac.web.chrome import ITemplateProvider


class BlackMagicTicketTweaks(Component):
    implements(ITemplateStreamFilter, ITemplateProvider, IPermissionRequestor,
               ITicketManipulator, IPermissionPolicy, IRequestFilter,
               IPermissionStore)

    gray_disabled = Option('blackmagic', 'gray_disabled', '', """
        If not set, disabled items will have a label with strike-through font.
        Otherwise, this color will be used to gray them out. Suggested
        value is `#cccccc`.""")

    permissions = ListOption('blackmagic', 'permissions', [], doc="""
        List of user-defined permissions (Deprecated in 0.12 in favor of Trac's
        `tracopt.perm.config_perm_provider.ExtraPermissionsProvider` component,
        see TracPermissions#CreatingNewPrivileges)""")

    def __init__(self):
        self.enchants = dict()
        self.extra_permissions = []
        self.blockedTickets = 0
        tweaks = self.config.get('blackmagic', 'tweaks', '')
        self.env.log.debug("Tweaks %s " % tweaks)
        for e in (x.strip() for x in tweaks.split(',')):
            self.enchants[e] = dict()
            self.enchants[e]['permission'] = \
                self.config.get('blackmagic', '%s.permission' % e, '').upper()
            self.enchants[e]['disable'] = \
                self.config.get('blackmagic', '%s.disable' % e, False)
            self.enchants[e]['hide'] = \
                self.config.get('blackmagic', '%s.hide' % e, False)
            self.enchants[e]['label'] = \
                self.config.get('blackmagic', '%s.label' % e, None)
            self.enchants[e]['notice'] = \
                self.config.get('blackmagic', '%s.notice' % e, None)
            self.enchants[e]['tip'] = \
                self.config.get('blackmagic', '%s.tip' % e, None)
            self.enchants[e]['ondenial'] = \
                self.config.get('blackmagic', '%s.ondenial' % e, 'disable')
        self.env.log.debug("Enchants %s " % self.enchants)

    # IPermissionPolicy(Interface)
    def check_permission(self, action, username, resource, perm):
        # skip if permission is in ignore_permissions
        if action in self.permissions or action in self.extra_permissions:
            return None

        # look up the resource parentage for a ticket.
        while resource:
            if resource.realm == 'ticket':
                break
            resource = resource.parent
        if resource and resource.realm == 'ticket' and resource.id is not None:
            # return if this req is permitted access to the given ticket ID.
            try:
                ticket = Ticket(self.env, resource.id)
            except TracError:
                return None  # Ticket doesn't exist
            # get perm for ticket type
            ticket_perm = self.config.get('blackmagic', 'ticket_type.%s'
                                                        % ticket['type'], None)
            if not ticket_perm:
                ticket_perm = None
            self.env.log.debug("Ticket permissions %s type %s "
                               % (ticket_perm, ticket['type']))
            if ticket_perm is None:
                #perm isn't set, return
                self.env.log.debug("Perm isn't set for ticket type %s"
                                   % ticket['type'])
                return None
            if ticket_perm not in self.permissions:
                # perm not part of blackmagic perms, adding to extra perms to
                # prevent recursion crash
                self.extra_permissions.append(ticket_perm)
                self.env.log.debug("Perm %s no in permissions " % ticket_perm)
            # user doesn't have permissions, return false
            if ticket_perm not in perm:
                self.env.log.debug("User %s doesn't have permission %s"
                                   % (username, ticket_perm))
                self.blockedTickets += 1
                return False
        return None

    ### IRequestFilter methods

    def pre_process_request(self, req, handler):
        return handler

    def post_process_request(self, req, template, data, content_type):

        if template == 'ticket.html':
            # remove ticket types user doesn't have permission to access
            for i, field in enumerate(data['fields']):
                if field['name'] == 'type':
                    allowed_types = []
                    for type in field['options']:
                        # get perm for ticket type
                        ticket_perm = self.config.get('blackmagic',
                                                      'ticket_type.%s' % type)
                        self.env.log.debug("Checking ticket permissions %s for "
                                           "type %s" % (ticket_perm, type))
                        if not ticket_perm or ticket_perm in req.perm:
                            # user has perm, add to allowed_types
                            allowed_types.append(type)
                            self.env.log.debug("User %s has permission %s"
                                               % (req.authname, ticket_perm))
                    data['fields'][i]['options'] = allowed_types

        if template == 'report_view.html':
            if 'numrows' in data:
                data['numrows'] -= self.blockedTickets
                # reset blocked tickets to 0
                self.blockedTickets = 0
            for row in data.get('row_groups', []):
                for l in row:
                    if isinstance(l, list):
                        for t in l:
                            tid = t.get('id') or t.get('ticket')
                            if not tid:
                                continue
                            for cell_group in t.get('cell_groups', []):
                                for field in cell_group:
                                    c = field['header']['col'].lower()
                                    if c in self.enchants:
                                        e = self.enchants[c]
                                        # hide hidden fields
                                        if e['hide']:
                                            field['value'] = ''
                                        # hide fields user doesn't have
                                        # permission to and they have
                                        # ondenial = hide
                                        perms = (x.strip() for x in
                                                 e['permission'].split(','))
                                        if e['permission'] != '' and \
                                                e['ondenial'] == 'hide':
                                            for perm in perms:
                                                denied = True
                                                if perm and perm in \
                                                        req.perm('ticket', tid):
                                                    denied = False
                                                if denied:
                                                    field['value'] = ''
                                        # re-label fields
                                        if e['label'] is not None:
                                            field['header']['title'] = \
                                                e['label']

        if template == 'query.html':
            # remove ticket types user doesn't have permission to access
            if 'type' in data['fields']:
                allowed_types = []
                for type in data['fields']['type']['options']:
                    # get perm for ticket type
                    ticket_perm = self.config.get('blackmagic',
                                                  'ticket_type.%s' % type)
                    self.env.log.debug("Ticket permissions %s type %s "
                                       % (ticket_perm, type))
                    if not ticket_perm or ticket_perm in req.perm:
                        # user has perm, add to allowed_types
                        allowed_types.append(type)
                        self.env.log.debug("User %s has permission %s"
                                           % (req.authname, ticket_perm))
                data['fields']['type']['options'] = allowed_types
            # remove ticket fields user doesn't have access to
            for i in range(len(data['tickets'])):
                ticket = data['tickets'][i]
                for c in ticket:
                    if c in self.enchants:
                        # hide hidden fields
                        e = self.enchants[c]
                        if e['hide']:
                            data['tickets'][i][c] = ''
                        # hide fields user doesn't have permission to and they
                        # have ondenial = hide
                        if e['permission'] != '' and e['ondenial'] == 'hide':
                            for perm in (x.strip() for x in
                                         e['permission'].split(',')):
                                denied = True
                                if perm and perm in \
                                        req.perm('ticket', ticket['id']):
                                    denied = False
                                if denied:
                                    data['tickets'][i][c] = ''
            # headers
            for i in range(len(data['headers'])):
                c = data['headers'][i]['name']
                if c in self.enchants:
                    # re-label fields
                    if self.enchants[c]['label'] is not None:
                        data['headers'][i]['label'] = self.enchants[c]['label']
            # fields
            for c, v in data['fields'].items():
                if c in self.enchants:
                    #re-label fields
                    if self.enchants[c]['label'] is not None:
                        data['fields'][c]['label'] = self.enchants[c]['label']

        return template, data, content_type

    ### ITicketManipulator methods

    def validate_ticket(self, req, ticket):
        """Validate a ticket after it's been populated from user input.

        Must return a list of `(field, message)` tuples, one for each problem
        detected. `field` can be `None` to indicate an overall problem with the
        ticket. Therefore, a return value of `[]` means everything is OK."""

        res = []
        self.env.log.debug('Validating ticket: %s' % ticket.id)

        for e, v in self.enchants.items():
            editable = True
            self.env.log.debug('%s' % v)
            if ticket.values.get(e, None) is not None:
                if v['disable'] or v['hide']:
                    editable = False
                elif v['permission'] != '':
                    editable = False
                    for perm in (x.strip() for x in v['permission'].split(',')):
                        self.env.log.debug("Checking permission %s" % perm)
                        # user has permission no denied
                        if perm and perm in req.perm(ticket.resource):
                            self.env.log.debug("Has %s permission" % perm)
                            editable = True

            # field is disabled or hidden, cannot be modified by user
            if not editable:
                self.env.log.debug("%s disabled or hidden " % e)
                # get default ticket state or original ticket if being modified
                ot = model.Ticket(self.env, ticket.id)
                original = ot.values.get('%s' % e, None)
                new = ticket.values.get('%s' % e, None)
                self.env.log.debug('OT: %s' % original)
                self.env.log.debug('NEW: %s' % new)
                # field has been modified throw error
                if new != original:
                    res.append(('%s' % e, 'Access denied to modifying %s' % e))
                    self.env.log.debug('Denied access to: %s' % e)

        # check if user has perm to create ticket type
        ticket_type = 'ticket_type.%s' % ticket['type']
        ticket_perm = self.config.get('blackmagic', ticket_type, None)
        if not ticket_perm:
            ticket_perm = None
        if ticket_perm is not None and ticket_perm not in req.perm:
            self.env.log.debug("Ticket validation failed type %s permission %s"
                               % (ticket['type'], ticket_perm))
            res.append(('type', "Access denied to ticket type %s"
                                % ticket['type']))
        return res

    ### IPermissionRequestor methods

    def get_permission_actions(self):
        return (x.upper() for x in self.permissions)

    ### ITemplateStreamFilter methods

    def filter_stream(self, req, method, filename, stream, data):
        # remove matches from custom queries due to the fact ticket permissions
        # are checked after this stream is manipulated so the count cannot be
        # updated.
        if filename == 'query.html':
            stream |= Transformer('//div[@class="query"]/h1'
                                  '/span[@class="numrows"]/text()').replace('')

        if filename == 'ticket.html':
            for field, e in self.enchants.items():
                disabled = e['disable']
                hidden = e['hide']
                # permissions are set for field
                if e['permission'] != '' and not hidden and not \
                        (disabled or disabled and e['ondenial'] == 'hide'):
                    self.env.log.debug("Permissions %s" % e['permission'])
                    # default set to denied
                    denied = True
                    # iterate through permissions
                    for perm in (x.strip() for x in e['permission'].split(',')):
                        self.env.log.debug("Checking permission %s" % perm)
                        # user has permission no denied
                        if perm and \
                                perm in req.perm(data.get('ticket').resource):
                            self.env.log.debug("Has %s permission" % perm)
                            denied = False
                    # if denied is true hide/disable depending on denial setting
                    if denied:
                        denial = self.config.get('blackmagic',
                                                 '%s.ondenial' % field, None)
                        if denial:
                            if denial == 'disable':
                                disabled = True
                            elif denial == 'hide':
                                hidden = True
                            else:
                                disabled = True
                        else:
                            disabled = True

                # hide fields
                if hidden:
                    # replace th and td in previews with empty tags
                    stream |= Transformer('//th[@id="h_%s"]' % field) \
                        .replace(tag.th(' '))
                    stream |= Transformer('//td[@headers="h_%s"]' % field)\
                        .replace(tag.td(' '))
                    # replace labels and fields with blank space
                    stream |= Transformer('//label[@for="field-%s"]' % field) \
                        .replace(' ')
                    stream |= Transformer('//*[@id="field-%s"]' % field). \
                        replace(' ')

                # change label
                if e['label'] is not None:
                    stream |= Transformer(
                        '//th[@id="h_%s"]/text()' % field) \
                        .replace(e['label'] + ":")
                    stream |= Transformer(
                        '//label[@for="field-%s"]/text()' % field). \
                        replace(e['label'] + ":")

                if disabled:
                    sbuffer = StreamBuffer()
                    # copy input to buffer then disable original
                    stream |= Transformer(
                        '//*[@id="field-%s" and (@checked) '
                        'and @type="checkbox"]'
                        % field).copy(sbuffer).after(sbuffer).attr('disabled',
                                                                   'disabled')
                    # change new element to hidden field instead of checkbox
                    # and remove check
                    stream |= Transformer(
                        '//*[@id="field-%s" and not (@disabled) and '
                        '(@checked) and @type="checkbox"]' % field) \
                        .attr('type', 'hidden').attr('checked', None) \
                        .attr('id', None)
                    # disable non-check boxes / unchecked check boxes
                    stream |= Transformer(
                        '//*[@id="field-%s" and not (@checked)]' % field) \
                        .attr('disabled', 'disabled')

                    if not self.gray_disabled:
                        # cut label content into buffer then append it into the
                        # label with a strike tag around it
                        stream |= Transformer(
                            '//label[@for="field-%s"]/text()' % field) \
                            .cut(sbuffer).end() \
                            .select('//label[@for="field-%s"]/' % field) \
                            .append(tag.strike(sbuffer))
                    else:
                        #cut label and replace with coloured span
                        stream |= Transformer(
                            '//label[@for="field-%s"]/text()' % field) \
                            .cut(sbuffer).end() \
                            .select('//label[@for="field-%s"]/' % field) \
                            .append(
                                tag.span(sbuffer, style='color:%s'
                                                        % self.gray_disabled)
                            )

                if self.config.get('blackmagic', '%s.notice' % field, None):
                    stream |= Transformer('//*[@id="field-%s"]' % field).after(
                        tag.br() + tag.small()(
                            tag.em()(
                                Markup(self.config.get('blackmagic',
                                                       '%s.notice' % field))
                            )
                        )
                    )

                tip = self.config.get('blackmagic', '%s.tip' % field, None)
                if tip:
                    stream |= Transformer('//div[@id="banner"]').before(
                        tag.script(type='text/javascript',
                                   src=req.href.chrome('blackmagic', 'js',
                                                       'wz_tooltip.js'))()
                    )

                    stream |= Transformer('//*[@id="field-%s"]' % field) \
                        .attr('onmouseover',
                              "Tip('%s')" % tip.replace(r"'", r"\'"))

        return stream

    ### ITemplateProvider methods

    def get_htdocs_dirs(self):
        from pkg_resources import resource_filename
        return [('blackmagic', resource_filename(__name__, 'htdocs'))]

    def get_templates_dirs(self):
        return []
