import logging
import urllib
import urllib2
import hashlib
 
from google.appengine.api import mail
from google.appengine.ext import webapp, db
from google.appengine.api import urlfetch, memcache, users
from google.appengine.ext.webapp import util, template
from google.appengine.api.labs import taskqueue
from django.utils import simplejson
from django.template.defaultfilters import timesince 

import dojo_name_api, keys, notify_io, logging, cgi

#CONSTANTS#
UPDATES_LIMIT = 100
DOMAIN = "@gmail.com"
SENDER_MAIL = "HD-Logs <santiago1717@gmail.com>"
APP_NAMES = ["Kudos", "Signin","Events"]
APP_NAMES_NO_NOTIFY = ["Signin","Events"]

# Parsing the username ourselfs because the nickname on GAE does funky stuff with non @gmail account
def username(user):
    return user.nickname().split('@')[0] if user else None

def str_to_bool(str):
    if str == "true": return True
    else: return False

def sanitizeHtml(value):
    return cgi.escape(value)

def sendNotifyIoNotifications(update):
    profiles = Profile.all().filter('notifyIoNotification =',True)
    for profile in profiles:
      taskqueue.add(url='/notifications/notifyio/post', params={'email': profile.user, 'text':update.user_fullname() + ":" + update.body, 'title':"New HD-Log"})

def sendEmailNotifications(update):
    body = "Someone just posted on HD-Logs\n Log: " + update.body + "\n Wrote by:" + update.user_fullname()
    profiles = Profile.all().filter('emailNotification =',True)
    for profile in profiles:
        taskqueue.add(url='/notifications/email/send', params={'to':profile.user,'body':body})

# Worket to handle the fullname queue request.
class UserWorker(webapp.RequestHandler):
    def post(self):
        month_ttl = 3600*24*28
        username = self.request.get('username')
        try:
            index =  APP_NAMES.index(name)
        except ValueError:
            index = -1

        if index != -1:   
            memcache.set('/users/%s:fullname' % username, username, month_ttl)
        user = dojo_name_api.dojo_name('/users/%s' % username, month_ttl)
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
    image_url = db.StringProperty()

    def user_fullname(self):
      return dojo_name_api.fullname(username(self.user))

class Comment(db.Model):
    user = db.UserProperty(auto_current_user_add=True)
    body = db.StringProperty(required=True)
    created = db.DateTimeProperty(auto_now_add=True)
    update = db.ReferenceProperty(Update)
    image_url = db.StringProperty()

    def user_fullname(self):
      return dojo_name_api.fullname(username(self.user))

#Json representations
def comment_dict(comment):
  return {
    'id': str(comment.key().id()),
    'user_fullname': comment.user_fullname(),
    'body': comment.body,
    'image_url':comment.image_url,
    'ago': timesince(comment.created)}

def updates_dict(update):
  return {
    'id':str(update.key().id()),
    'user_fullname':update.user_fullname(),
    'body':update.body,
    'ago':timesince(update.created),
    'image_url':update.image_url,
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
        body = sanitizeHtml(self.request.get('body'))
        if update and len(body) > 0 and len(body) < 500:
            image = 'http://0.gravatar.com/avatar/%s' % hashlib.md5(str(users.get_current_user()) + DOMAIN).hexdigest()
            comment = Comment(
                body=body,
                update=update,
                image_url=image)
            comment.put()
        self.redirect('/')

class ApiHandler(webapp.RequestHandler):
    def post(self):
        body = sanitizeHtml(self.request.get('body'))
        name = sanitizeHtml(self.request.get('name'))
        key = self.request.get('key')
        if body == "" or name == "" or key == "":
            self.response.out.write("body,name and key are required")
            return 
        if key == keys.logs_key:
            try:
                index =  APP_NAMES.index(name)
            except ValueError:
                index = -1

            if index != -1:
                user = users.User(name + DOMAIN)
                update = Update(body=body,image_url="/static/dojo_icon.png",user=user)
                update.put()
                try:
                    index =  APP_NAMES_NO_NOTIFY.index(name)
                except ValueError:
                    index = -1
                if index == -1:
                    sendNotifyIoNotifications(update)
                    sendEmailNotifications(update)
                self.response.out.write("OK")
            else:
                self.response.out.write("Not a valid App")
        else:
            self.response.out.write("Invalid Key")

class MainHandler(webapp.RequestHandler):
    def get(self):
        user = users.get_current_user()
        if user:
            logout_url = users.create_logout_url('/')
        else:
            login_url = users.create_login_url('/')
        updates_query = Update.all().order('-created')
        updates = updates_query.fetch(UPDATES_LIMIT)
        profile = Profile.get_or_create()
        self.response.out.write(template.render('templates/main.html', locals()))
    
    def post(self):
        image = 'http://0.gravatar.com/avatar/%s' % hashlib.md5(str(users.get_current_user()) + DOMAIN).hexdigest()
        body = sanitizeHtml(self.request.get('body'))
        if len(body) > 0 and len(body) < 500:
            update = Update(body=body,image_url=image)
            sendEmailNotifications(update)
            sendNotifyIoNotifications(update)
            update.put()
        self.redirect('/')

class EmailSendNotificationHandler(webapp.RequestHandler):
    def post(self):
        sender = SENDER_MAIL 
        subject = "New HD-Log"
        message = mail.EmailMessage(sender=sender,subject=subject)
        message.body = self.request.get('body')
        message.to = self.request.get('to') + DOMAIN
        message.send()

#this is used to turn off/on the email for a user
class EmailEnableNotificationHandler(webapp.RequestHandler):
    def post(self):
        user = Profile.get_or_create()
        user.emailNotification = str_to_bool(self.request.get('enable'))
        user.put()

#This is used by the taskqueue to actually send the notification
class NotifyIoPostNotificationHandler(webapp.RequestHandler):
    def post(self):
        email = self.request.get('email') + DOMAIN
        text = self.request.get('text')
        title = self.request.get('title')
        logging.info('Sending a Notify.io message to %s' % email)
        notify_io.notify(email, text, title)

# This is used to turn off/on the notifications for a user
class NotifyIoEnableNotificationHandler(webapp.RequestHandler):
    def post(self):
        user = Profile.get_or_create()
        user.notifyIoNotification = str_to_bool(self.request.get('enable'))
        user.put()

def main():
    application = webapp.WSGIApplication([
        ('/', MainHandler),
        ('/updates/(.+)', UpdatesHandler),
        ('/comment/(.+)', CommentHandler),
        ('/api', ApiHandler),
        ('/notifications/email', EmailEnableNotificationHandler),
        ('/notifications/email/send', EmailSendNotificationHandler),
        ('/notifications/notifyio', NotifyIoEnableNotificationHandler),
        ('/notifications/notifyio/post', NotifyIoPostNotificationHandler),
        ('/worker/user', UserWorker),
      ], debug=True)
    util.run_wsgi_app(application)

if __name__ == '__main__':
    main()
