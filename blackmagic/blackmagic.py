from trac.core import Component, implements, TracError
from trac.config import Option, IntOption, ListOption, BoolOption
from trac.web.chrome import ITemplateProvider, add_stylesheet, add_script
from trac.ticket.api import ITicketManipulator
from trac.ticket import model
from pkg_resources import resource_filename
from trac.web.api import ITemplateStreamFilter, IRequestFilter
from genshi.builder import tag
from genshi.core import Markup
from genshi.filters.transform import Transformer
from genshi.filters.transform import StreamBuffer
import re, cPickle
from trac.perm import IPermissionRequestor, IPermissionPolicy, DefaultPermissionStore, IPermissionStore
from trac.ticket.model import Ticket

def istrue(v, otherwise=None):
    if str(v).lower() in ('yes', 'true', '1', 'on'):
        return True
    else:
        if otherwise is None:
            return False
        else:
            return otherwise

class BlackMagicTicketTweaks(Component):
    implements(ITemplateStreamFilter, ITemplateProvider, IPermissionRequestor, ITicketManipulator, IPermissionPolicy, IRequestFilter, IPermissionStore)
    
    permissions = ListOption('blackmagic', 'permissions', [])
    enchants = dict()
        
    #used to store extra permissions to prevent recursion when using non-blackmagic permissions for ticket options
    extra_permissions = []
    
    gray_disabled = Option('blackmagic', 'gray_disabled', '',
        doc="""If not set, disabled items will have their label striked through.
        Otherwise, this color will be used to gray them out. Suggested #cccccc.""")
    
    #stores the number of blocked tickets used for matching the count on reports
    blockedTickets = 0
    
    def __init__(self):
        tweaks = self.config.get('blackmagic','tweaks','');
        self.env.log.debug("Tweaks %s " %  tweaks)
        for e in (x.strip() for x in tweaks.split(',')):
            self.enchants[e]=dict()
            self.enchants[e]["permission"]=self.config.get('blackmagic', '%s.permission' % e, '').upper()
            self.enchants[e]["disable"]=self.config.get('blackmagic','%s.disable' % e, False)
            self.enchants[e]["hide"]=self.config.get('blackmagic','%s.hide' % e, False)
            self.enchants[e]["label"]=self.config.get('blackmagic','%s.label' % e, None)
            self.enchants[e]["notice"]=self.config.get('blackmagic','%s.notice' % e, None)
            self.enchants[e]["tip"]=self.config.get('blackmagic', '%s.tip' % e, None)
            self.enchants[e]["ondenial"]=self.config.get('blackmagic','%s.ondenial' % e, "disable")
        self.env.log.debug("Enchants %s " %  self.enchants)
    
    # IPermissionPolicy(Interface)
    def check_permission(self, action, username, resource, perm):
        #skip if permission is in ignore_permissions
        if action in self.permissions or action in self.extra_permissions:
            return None

        # Look up the resource parentage for a ticket.
        while resource:
            if resource.realm == 'ticket':
                break
            resource = resource.parent
        if resource and resource.realm == 'ticket' and resource.id is not None:
            """Return if this req is permitted access to the given ticket ID."""
            try:
                ticket = Ticket(self.env, resource.id)
            except TracError:
                return None # Ticket doesn't exist
            #get perm for ticket type
            ticketperm = self.config.get('blackmagic','ticket_type.%s' % ticket["type"], None)
            if not ticketperm:
                ticketperm = None
            self.env.log.debug("Ticket permissions %s type %s " % (ticketperm,ticket["type"]) );
            if ticketperm is None:
                #perm isn't set, return
                self.env.log.debug("Perm isn't set for ticket type %s" % ticket["type"]);
                return None
            if not ticketperm in self.permissions:
                #perm not part of blackmagic perms, adding to extra perms to prevent recursion crash
                self.extra_permissions.append(ticketperm)
                self.env.log.debug("Perm %s no in permissions " % ticketperm)
            #user doesn't have permissions, return false
            if ticketperm not in perm:
                self.env.log.debug("User %s doesn't have permission %s" % (username, ticketperm) );
                self.blockedTickets+=1
                return False
        return None
    
    
    #IRequestFilter methods

    def pre_process_request(self, req, handler):
        return handler
    def post_process_request(self, req, template, data, content_type):
        if template == "report_view.html":
            data["numrows"]-=self.blockedTickets;
        #reset blocked tickets to 0
        self.blockedTickets = 0
        #ticket page
        if template == "ticket.html":
            #remove ticket types user doesn't have permission to
            fields = data.get("fields")
            i = 0
            for type in fields:
                if  type.get("name") == "type":
                    newTypes = []
                    for option in type.get("options"):
                        #get perm for ticket type
                        ticketperm = self.config.get('blackmagic','ticket_type.%s' % option, None)
                        if not ticketperm:
                            ticketperm = None
                        self.env.log.debug("Ticket permissions %s type %s " % (ticketperm,option) );
                        if ticketperm is None or ticketperm in req.perm:
                            #user has perm, add to newTypes
                            newTypes.append(option)
                            self.env.log.debug("User %s has permission %s" % (req.authname, ticketperm) );
                    data["fields"][i]["options"]=newTypes
                i+=1
        #report page        
        if template == "report_view.html":
                    newItems = []
                    for row in data["row_groups"]:
                        for l in row:
                            if isinstance(l,list):
                              for t in l:
                                id = t["id"]
                                for cell_group in t["cell_groups"]:
                                    for group in cell_group:
                                        for field in cell_group:
                                            c = field["header"]["col"].lower()
                                            if c in self.enchants:
                                                #hide hidden fields
                                                if self.enchants[c]["hide"]:
                                                    field["value"]=''
                                                #hide fields user doesn't have permission to and they have ondenial = hide    
                                                if self.enchants[c]["permission"] != '' and self.enchants[c]["ondenial"]=="hide":
                                                    for perm in (x.strip() for x in self.enchants[c]["permission"].split(',')):
                                                        denied = True
                                                        if perm and perm in req.perm(Ticket(self.env,id).resource):
                                                            denied = False
                                                        if denied:
                                                            field["value"]=''
                                                #re-label fields            
                                                if self.enchants[c]["label"] is not None:
                                                    field["header"]["title"]=self.enchants[c]["label"]
        #query page                                                            
        if template == "query.html":
            #remove ticket types user doesn't have permission to
            if "type" in data["fields"]:
                newTypes = []
                for option in data["fields"]["type"]["options"]:
                    #get perm for ticket type
                    ticketperm = self.config.get('blackmagic','ticket_type.%s' % option, None)
                    if not ticketperm:
                        ticketperm = None
                    self.env.log.debug("Ticket permissions %s type %s " % (ticketperm,option) );
                    if ticketperm is None or ticketperm in req.perm:
                        #user has perm, add to newTypes
                        newTypes.append(option)
                        self.env.log.debug("User %s has permission %s" % (req.authname, ticketperm) );
                data["fields"]["type"]["options"] = newTypes
            #remove ticket fields user doesn't have access to
            for i in range(len(data["tickets"])):
                ticket = data["tickets"][i]
                for c in ticket:
                    if c in self.enchants:
                        #hide hidden fields
                        if self.enchants[c]["hide"]:
                           data["tickets"][i][c]=''
                        #hide fields user doesn't have permission to and they have ondenial = hide    
                        if self.enchants[c]["permission"] != '' and self.enchants[c]["ondenial"]=="hide":
                            for perm in (x.strip() for x in self.enchants[c]["permission"].split(',')):
                                denied = True
                                if perm and perm in req.perm(Ticket(self.env,ticket["id"]).resource):
                                    denied = False
                                if denied:
                                    data["tickets"][i][c]=''
            #headers            
            for i in range(len(data["headers"])):
                c = data["headers"][i]["name"]
                if c in self.enchants:
                    #re-label fields            
                    if self.enchants[c]["label"] is not None:
                        data["headers"][i]["label"]=self.enchants[c]["label"]
            #fields            
            for c,v in data["fields"].items():
                if c in self.enchants:
                    #re-label fields            
                    if self.enchants[c]["label"] is not None:
                        data["fields"][c]["label"]=self.enchants[c]["label"]
        return template, data, content_type
    

    # ITicketManipulator methods

    def validate_ticket(self, req, ticket):
        """Validate a ticket after it's been populated from user input.

        Must return a list of `(field, message)` tuples, one for each problem
        detected. `field` can be `None` to indicate an overall problem with the
        ticket. Therefore, a return value of `[]` means everything is OK."""

        res = []
        self.env.log.debug('Validating ticket: %s' % ticket.id)

        enchants = self.config.get('blackmagic', 'tweaks', '')
        for e,v in self.enchants.items():
            editable = True
            self.env.log.debug('%s' % v)
            if ticket.values.get(e, None) is not None:
                if v["disable"] or v["hide"]:
                    editable = False
                elif v["permission"]!='':
                    editable = False
                    for perm in (x.strip() for x in v["permission"].split(',')):
                        self.env.log.debug("Checking permission %s" % perm)
                        #user has permission no denied
                        if perm and perm in req.perm(ticket.resource):
                           self.env.log.debug("Has %s permission" % perm)
                           editable = True
                    
        
            #field is disabled or hidden, cannot be modified by user
            if not editable:
                self.env.log.debug('%s disabled or hidden ' % e)
                #get default ticket state or orginal ticket if being modified
                ot = model.Ticket(self.env, ticket.id)
                original = ot.values.get('%s' % e, None)
                new = ticket.values.get('%s' % e, None)
                self.env.log.debug('OT: %s' % original)
                self.env.log.debug('NEW: %s' % new)
                #field has been modified throw error
                if new != original:
                    res.append(('%s' % e, 'Access denied to modifying %s' % e))
                    self.env.log.debug('Denied access to: %s' % e)
        
        #check if user has perm to create ticket type
        ticketperm = self.config.get("blackmagic","ticket_type.%s" % ticket["type"],None)
        if not ticketperm:
            ticketperm = None
        if ticketperm is not None and ticketperm not in req.perm:
            self.env.log.debug("Ticket validation failed type %s permission %s"% (ticket["type"], ticketperm))
            res.append(('type', "Access denied to ticket type %s" % ticket["type"]))
            
        return res



    ## IPermissionRequestor methods

    def get_permission_actions(self):
        return (x.upper() for x in self.permissions)

    ## ITemplateStreamFilter

    def filter_stream(self, req, method, filename, stream, data):
        #remove matches from custom queries due to the fact ticket permissions are checked after this stream is manipulated so the count cannot be updated.
        if filename == "query.html":
            stream |= Transformer('//div[@class="query"]/h1/span[@class="numrows"]/text()').replace("")

        if filename == "ticket.html":
            for field,e in self.enchants.items():
                disabled = e["disable"]
                hidden = e["hide"]
                #permissions are set for field
                if e["permission"] != "" and not hidden and not (disabled or disabled and e["ondenial"]=="hide"):
                    self.env.log.debug("Permissions %s" % e["permission"])
                    #default set to denied
                    denied = True
                    #iterate through permissions
                    for perm in (x.strip() for x in e["permission"].split(',')):
                        self.env.log.debug("Checking permission %s" % perm)
                        #user has permission no denied
                        if perm and perm in req.perm(data.get("ticket").resource):
                            self.env.log.debug("Has %s permission" % perm)
                            denied = False
                    #if denied is true hide/disable dpending on denial setting
                    if denied:
                        denial = self.config.get('blackmagic', '%s.ondenial' % field, None)
                        if denial:
                            if denial == "disable":
                                disabled = True
                            elif denial == "hide":
                                hidden = True
                            else:
                                disabled = True
                        else:
                                disabled = True

                #hide fields
                if hidden:
                    #replace th and td in previews with empty tags
                    stream = stream | Transformer('//th[@id="h_%s"]' % field).replace(tag.th(" "))
                    stream = stream | Transformer('//td[@headers="h_%s"]' % field).replace(tag.td(" "))
                    #replace labels and fields with blank space
                    stream = stream | Transformer('//label[@for="field-%s"]' % field).replace(" ")
                    stream = stream | Transformer('//*[@id="field-%s"]' % field).replace(" ")

                #change label
                if e["label"] is not None:
                    stream |= Transformer('//th[@id="h_%s"]/text()' % field).replace(e["label"])
                    stream = stream | Transformer('//label[@for="field-%s"]/text()' % field).replace(e["label"])

                if disabled:
                    buffer = StreamBuffer()
                    #copy input to buffer then disable original
                    stream |= Transformer('//*[@id="field-%s" and (@checked) and @type="checkbox"]' % field).copy(buffer).after(buffer).attr("disabled","disabled")
                    #change new element to hidden field instead of checkbox and remove check
                    stream |= Transformer('//*[@id="field-%s" and not (@disabled) and (@checked) and @type="checkbox"]' % field).attr("type","hidden").attr("checked",None).attr("id",None)
                    #disable non-check boxes / unchecked check boxes
                    stream = stream | Transformer('//*[@id="field-%s" and not (@checked)]' % field).attr("disabled", "disabled")

                    if not self.gray_disabled:
                        #cut label content into buffer then append it into the label with a strike tag around it
                        stream = stream | Transformer('//label[@for="field-%s"]/text()' % field).cut(buffer).end().select('//label[@for="field-%s"]/' % field).append(tag.strike(buffer))
                    else:
                        #cut label and replace with coloured span
                        stream = stream | Transformer('//label[@for="field-%s"]/text()' % field).cut(buffer).end().select('//label[@for="field-%s"]/' % field).append(tag.span(buffer, style="color:%s" % self.gray_disabled))

                if self.config.get('blackmagic', '%s.notice' % field, None):
                    stream = stream | Transformer('//*[@id="field-%s"]' % field).after(
                        tag.br() + tag.small()(
                            tag.em()(
                                Markup(self.config.get('blackmagic', '%s.notice' % field))
                            )
                        )
                    )

                tip = self.config.get('blackmagic', '%s.tip' % field, None)
                if tip:
                    stream = stream | Transformer('//div[@id="banner"]').before(
                        tag.script(type="text/javascript",
                        src=req.href.chrome("blackmagic", "js", "wz_tooltip.js"))()
                    )

                    stream = stream | Transformer('//*[@id="field-%s"]' % field).attr(
                        "onmouseover", "Tip('%s')" % tip.replace(r"'", r"\'")
                    )


        return stream

    ## ITemplateProvider

    def get_htdocs_dirs(self):
        from pkg_resources import resource_filename
        return [('blackmagic', resource_filename(__name__, 'htdocs'))]

    def get_templates_dirs(self):
        return []