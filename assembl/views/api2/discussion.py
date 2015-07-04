from functools import partial
import re
import base64
from cStringIO import StringIO
from os import urandom
from itertools import chain
from collections import defaultdict

import simplejson as json
from pyramid.response import Response
from pyramid.view import view_config
from pyramid.httpexceptions import (
    HTTPOk, HTTPBadRequest, HTTPUnauthorized, HTTPNotAcceptable)
from pyramid_dogpile_cache import get_region
from pyramid.security import authenticated_userid
from pyramid.renderers import JSONP_VALID_CALLBACK

from assembl.auth import (
    P_READ, P_READ_PUBLIC_CIF, P_ADMIN_DISC, P_SYSADMIN, Everyone)
from assembl.auth.password import verify_data_token, data_token
from assembl.auth.util import get_permissions
from assembl.models import (Discussion, Permission)
from ..traversal import InstanceContext
from . import JSON_HEADER


@view_config(context=InstanceContext, request_method='GET',
             ctx_instance_class=Discussion, permission=P_READ,
             accept="application/json", name="settings",
             renderer='json')
def discussion_settings_get(request):
    return request.context._instance.settings_json


@view_config(context=InstanceContext, request_method='PATCH',
             ctx_instance_class=Discussion, permission=P_ADMIN_DISC,
             header=JSON_HEADER, name="settings")
@view_config(context=InstanceContext, request_method='PUT',
             ctx_instance_class=Discussion, permission=P_ADMIN_DISC,
             header=JSON_HEADER, name="settings")
def discussion_settings_put(request):
    request.context._instance.settings_json = request.json_body
    return HTTPOk()


discussion_jsonld_cache = get_region('discussion_jsonld')
userprivate_jsonld_cache = get_region('userprivate_jsonld')

@discussion_jsonld_cache.cache_on_arguments()
def discussion_jsonld(discussion_id):
    from assembl.semantic.virtuoso_mapping import AssemblQuadStorageManager
    aqsm = AssemblQuadStorageManager()
    return aqsm.as_jsonld(discussion_id)


@userprivate_jsonld_cache.cache_on_arguments()
def userprivate_jsonld(discussion_id):
    from assembl.semantic.virtuoso_mapping import AssemblQuadStorageManager
    aqsm = AssemblQuadStorageManager()
    cg = aqsm.participants_private_as_graph(discussion_id)
    return aqsm.graph_as_jsonld(cg)



def read_user_token(request):
    salt = None
    user_id = authenticated_userid(request)
    discussion_id = request.context.get_discussion_id()
    permissions = get_permissions(user_id or Everyone, discussion_id)
    if P_READ in permissions:
        permissions.append(P_READ_PUBLIC_CIF)

    if 'token' in request.GET:
        token = request.GET['token'].encode('ascii')
        data = verify_data_token(token)
        if data is None:
            raise HTTPBadRequest("Invalid token")
        try:
            data, salt = data.split('.', 1)
            salt = base64.urlsafe_b64decode(salt)
            data = [int(i) for i in data.split(',')]
            t_user_id, t_discussion_id = data[:2]
            req_permissions = data[2:]
            if len(req_permissions):
                req_permissions = [x for (x,) in Permission.default_db.query(
                    Permission.name).filter(
                    Permission.id.in_(req_permissions)).all()]
        except (ValueError, IndexError):
            raise HTTPBadRequest("Invalid token")
        if discussion_id is not None and t_discussion_id != discussion_id:
            raise HTTPUnauthorized("Token for another discussion")
        if user_id is None:
            permissions = get_permissions(t_user_id, discussion_id)
            if P_READ in permissions:
                permissions.append(P_READ_PUBLIC_CIF)
        elif t_user_id != user_id:
            raise HTTPUnauthorized("Token for another user")
        user_id = t_user_id
        permissions = set(permissions).intersection(set(req_permissions))
    return user_id, permissions, salt


def handle_jsonp(callback_fn, json):
    # TODO: Use an augmented JSONP renderer with ld content-type
    if not JSONP_VALID_CALLBACK.match(callback_fn):
        raise HTTPBadRequest("invalid callback name")
    return "/**/{0}({1});".format(callback_fn.encode('ascii'), json)


@view_config(context=InstanceContext, name="perm_token",
             ctx_instance_class=Discussion, request_method='GET',
             accept="application/ld+json")
def get_token(request):
    user_id = authenticated_userid(request)
    discussion_id = request.context.get_discussion_id()
    if not user_id:
        raise HTTPUnauthorized()
    req_permissions = request.GET.getall('permission') or [
        P_READ, P_READ_PUBLIC_CIF]
    random_seed = request.GET.get('seed', None)
    if random_seed:
        # We need some determinism
        import random
        random.seed(random_seed)
        random_str = ''.join([chr(random.randint(0,256)) for i in range(8)])
        random.seed(urandom(8))
    else:
        random_str = urandom(8)
    if isinstance(req_permissions, list):
        req_permissions = set(req_permissions)
    else:
        req_permissions = set((req_permissions,))
    permissions = set(get_permissions(user_id, discussion_id))
    if not req_permissions:
        req_permissions = permissions
    else:
        if P_READ in permissions:
            permissions.add(P_READ_PUBLIC_CIF)
        if P_SYSADMIN not in permissions:
            req_permissions = list(req_permissions.intersection(permissions))
    req_permissions = list(req_permissions)
    data = [str(user_id), str(discussion_id)]
    data.extend([str(x) for (x,) in Permission.default_db.query(
            Permission.id).filter(Permission.name.in_(req_permissions)).all()])
    data = ','.join(data) + '.' + base64.urlsafe_b64encode(random_str)
    return Response(body=data_token(data), content_type="text/text")


@view_config(context=InstanceContext, name="jsonld",
             ctx_instance_class=Discussion, request_method='GET',
             accept="application/ld+json")
@view_config(context=InstanceContext,
             ctx_instance_class=Discussion, request_method='GET',
             accept="application/ld+json")
def discussion_instance_view_jsonld(request):
    discussion = request.context._instance
    user_id, permissions, salt = read_user_token(request)
    if not (P_READ in permissions or P_READ_PUBLIC_CIF in permissions):
        raise HTTPUnauthorized()
    if not salt and P_ADMIN_DISC not in permissions:
        salt = base64.urlsafe_b64encode(urandom(6))

    jdata = discussion_jsonld(discussion.id)
    if salt:
        from assembl.semantic.virtuoso_mapping import (
            AssemblQuadStorageManager, hash_obfuscator)
        obfuscator = partial(hash_obfuscator, salt=salt)
        jdata = AssemblQuadStorageManager.obfuscate(jdata, obfuscator)
    # TODO: Add age
    if "callback" in request.GET:
        jdata = handle_jsonp(request.GET['callback'], jdata)
        content_type = "application/json-p"
    else:
        content_type = "application/ld+json"
    return Response(body=jdata, content_type=content_type)


@view_config(context=InstanceContext, name="private_jsonld",
             ctx_instance_class=Discussion, request_method='GET',
             accept="application/ld+json")
def user_private_view_jsonld(request):
    discussion_id = request.context.get_discussion_id()
    user_id, permissions, salt = read_user_token(request)
    if P_READ not in permissions:
        raise HTTPUnauthorized()
    if not salt and P_ADMIN_DISC not in permissions:
        salt = base64.urlsafe_b64encode(urandom(6))

    jdata = userprivate_jsonld(discussion_id)
    if salt:
        from assembl.semantic.virtuoso_mapping import (
            AssemblQuadStorageManager, hash_obfuscator)
        obfuscator = partial(hash_obfuscator, salt=salt)
        jdata = AssemblQuadStorageManager.obfuscate(jdata, obfuscator)
    if "callback" in request.GET:
        jdata = handle_jsonp(request.GET['callback'], jdata)
        content_type = "application/json-p"
    else:
        content_type = "application/ld+json"
    return Response(body=jdata, content_type=content_type)


@view_config(context=InstanceContext, name="contribution_count",
             ctx_instance_class=Discussion, request_method='GET',
             permission=P_ADMIN_DISC)
def get_contribution_count(request):
    import isodate
    from datetime import datetime
    start = request.GET.get("start", None)
    end = request.GET.get("end", None)
    interval = request.GET.get("interval", None)
    discussion = request.context._instance
    try:
        if start:
            start = isodate.parse_datetime(start)
        if end:
            end = isodate.parse_datetime(end)
        if interval:
            interval = isodate.parse_duration(interval)
    except isodate.ISO8601Error as e:
        raise HTTPBadRequest(e)
    if interval and not start:
        raise HTTPBadRequest("You cannot define an interval and no start")
    if interval and not end:
        end = datetime.now()
    results = []
    if interval:
        while start < end:
            this_end = min(start+interval, end)
            results.append(dict(
                start=start, end=this_end,
                count=discussion.count_contributions_per_agent(
                    start, this_end)))
            start = this_end
    else:
        r = dict(count=discussion.count_contributions_per_agent(start, end))
        if not start:
            from assembl.models import Post
            from sqlalchemy import func
            (start,) = discussion.db.query(func.min(Post.creation_date)
                ).filter_by(discussion_id=discussion.id).first()
        r["start"] = start
        if not end:
            end = datetime.now()
        r["end"] = end
        results.append(r)
    if (request.GET.get('format', None) == 'json'
            or request.accept == 'application/json'):
        for v in results:
            v['start'] = v['start'].isoformat()
            v['end'] = v['end'].isoformat()
            v['count'] = {agent.display_name(): count
                          for (agent, count) in v['count']}
        return Response(json.dumps(results), content_type='application/json')
    # otherwise assume csv
    from csv import writer
    total_count = defaultdict(int)
    agents = {}
    for v in results:
        as_dict = {}
        for (agent, count) in v['count']:
            total_count[agent.id] += count
            as_dict[agent.id] = count
            agents[agent.id] = agent
        v['count'] = as_dict
    count_list = total_count.items()
    count_list.sort(key=lambda (a, c): c, reverse=True)
    output = StringIO()
    csv = writer(output)
    csv.writerow(['Start']+[
        x['start'].isoformat() for x in results] + ['Total'])
    csv.writerow(['End']+[
        x['end'].isoformat() for x in results] + [''])
    for agent_id, total_count in count_list:
        agent = agents[agent_id]
        agent_name = (
            agent.display_name() or agent.real_name() or
            agent.get_preferred_email())
        csv.writerow([agent_name.encode('utf-8')] + [
            x['count'].get(agent_id, '') for x in results] + [total_count])
    output.seek(0)
    return Response(body_file=output, content_type='text/csv')


pygraphviz_formats = {
    'text/vnd.graphviz': 'dot',
    'image/gif': 'gif',
    'application/vnd.hp-hpgl': 'hpgl',
    'image/jpeg': 'jpeg',
    'application/vnd.mif': 'mif',
    'application/vnd.hp-pcl': 'pcl',
    'application/pdf': 'pdf',
    'image/x-pict': 'pic',
    'image/png': 'png',
    'application/postscript': 'ps',
    'image/svg+xml': 'svg',
    'model/vrml': 'vrml',
}

@view_config(context=InstanceContext, name="mindmap",
             ctx_instance_class=Discussion, request_method='GET',
             permission=P_READ)
def as_mind_map(request):
    for mimetype in request.GET.getall('mimetype'):
        mimetype = mimetype.encode('utf-8')
        if mimetype in pygraphviz_formats:
            break
    else:
        mimetype = request.accept.best_match(pygraphviz_formats.keys())
        if not mimetype:
            raise HTTPNotAcceptable("Not known to pygraphviz: "+mimetype)
    discussion = request.context._instance
    G = discussion.as_mind_map()
    G.layout(prog='twopi')
    io=StringIO()
    G.draw(io, format=pygraphviz_formats[mimetype])
    io.seek(0)
    return Response(body_file=io, content_type=mimetype)
