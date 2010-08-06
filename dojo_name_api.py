from google.appengine.api import urlfetch, memcache
from google.appengine.api.labs import taskqueue

# Hacker Dojo Domain API helper with caching
def dojo_name(path, cache_ttl=3600):
    base_url = 'http://domain.hackerdojo.com'
    resp = memcache.get(path)
    if not resp:
        resp = urlfetch.fetch(base_url + path, deadline=10)
        try:
            resp = simplejson.loads(resp.content)
        except Exception, e:
            resp = []
            cache_ttl = 10
        memcache.set(path, resp, cache_ttl)
    return resp

# Return the name of a user from the memcache. If it was not set we set it and queue a query to the domain api
def fullname(username):
    fullname = memcache.get('/users/%s:fullname' % username)
    if not fullname:
        taskqueue.add(url='/worker/user', params={'username': username})
        memcache.set('/users/%s:fullname' % username, username, 100)
        return username
    else:
        return fullname

