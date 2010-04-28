import logging
import urllib

from google.appengine.ext import webapp, db
from google.appengine.api import urlfetch, memcache, users
from google.appengine.ext.webapp import util, template
from google.appengine.api.labs import taskqueue
from django.utils import simplejson
from django.template.defaultfilters import timesince 

#CONSTANTS#
UPDATES_LIMIT = 10


# Parsing the username ourselfs because the nickname on GAE does funky stuff with non @gmail account
def username(user):
    return user.nickname().split('@')[0] if user else None

# Hacker Dojo Domain API helper with caching
def dojo(path, cache_ttl=3600):
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
        memcache.set('/users/%s:fullname' % username, username, 10)
        return username
    else:
        return fullname

# Worket to handle the fullname queue request.
class UserWorker(webapp.RequestHandler):
    def post(self):
        username = self.request.get('username')
        month_ttl = 3600*24*28
        user = dojo('/users/%s' % username, month_ttl)
        memcache.set('/users/%s:fullname' % username, "%s %s" % (user['first_name'], user['last_name']), month_ttl)

#Data Models:
class Profile(db.Model):
    user = db.UserProperty(auto_current_user_add=True)
    emailNotification = db.BooleanProperty(default=False)
    notifyIoNotification = db.BooleanProperty(default=False)

    @staticmethod
    def get_or_create():
        profile = Profile.all().filter('user =',users.get_current_user()).fetch(1)
        if len(profile) == 0:
            profile = Profile()
            profile.put()
            return profile
        else:
            return profile[0]

class Update(db.Model):
    user = db.UserProperty(auto_current_user_add=True)
    body = db.StringProperty(required=True, multiline=True)
    created = db.DateTimeProperty(auto_now_add=True)
    
    def user_fullname(self):
      return fullname(username(self.user))

class Comment(db.Model):
    user = db.UserProperty(auto_current_user_add=True)
    body = db.StringProperty(required=True)
    created = db.DateTimeProperty(auto_now_add=True)
    update = db.ReferenceProperty(Update)

    def user_fullname(self):
      return fullname(username(self.user))

#Json representations
def comment_dict(comment):
  return {
    'id': str(comment.key().id()),
    'user_fullname': comment.user_fullname(),
    'body': comment.body,
    'ago': timesince(comment.created)}

def updates_dict(update):
  return {
    'id':str(update.key().id()),
    'user_fullname':update.user_fullname(),
    'body':update.body,
    'ago':timesince(update.created),
    'comments':map(lambda c: comment_dict(c), update.comment_set) }

# Handlers:
class UpdatesHandler(webapp.RequestHandler):
    def get(self,cursor):
        updates_query = Update.all().order('-created')
        updates_with_cursor = updates_query.with_cursor(urllib.unquote(cursor)).fetch(UPDATES_LIMIT)
        self.response.out.write(simplejson.dumps([{'messages':map((lambda u: updates_dict(u)), updates_with_cursor)}, {'cursor':updates_query.cursor()}]))

class CommentHandler(webapp.RequestHandler):
    def post(self, update_id):
        update = Update.get_by_id(int(update_id))
        if update:
            comment = Comment(
                body=self.request.get('body'),
                update=update)
            comment.put()
        self.redirect('/')

class MainHandler(webapp.RequestHandler):
    def get(self):
        user = users.get_current_user()
        if user:
            logout_url = users.create_logout_url('/')
        else:
            login_url = users.create_login_url('/')
        updates_query = Update.all().order('-created')
        updates = updates_query.fetch(UPDATES_LIMIT)
        self.response.out.write(template.render('templates/main.html', locals()))
    
    def post(self):
        update = Update(body=self.request.get('body'))
        update.put()
        self.redirect('/')

class EmailNotificationHandler(webapp.RequestHandler):
    def post(self):
        user = Profile.get_or_create()
        user.emailNotification = str_to_bool(self.request.get('enable'))
        user.put()

class NotifyIoNotificationHandler(webapp.RequestHandler):
    def post(self):
        user = Profile.get_or_create()
        user.notifyIoNotification = str_to_bool(self.request.get('enable'))
        user.put()

def str_to_bool(str):
    if str == "true": return True
    else: return False

def main():
    application = webapp.WSGIApplication([
        ('/', MainHandler),
        ('/updates/(.+)', UpdatesHandler),
        ('/comment/(.+)', CommentHandler),
        ('/notifications/email', EmailNotificationHandler),
        ('/notifications/notifyio', NotifyIoNotificationHandler),
        ('/worker/user', UserWorker),
      ], debug=True)
    util.run_wsgi_app(application)


if __name__ == '__main__':
    main()
