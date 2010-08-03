from google.appengine.api import urlfetch
import urllib, hashlib, keys

# This notify method was taken from commitify @ http://github.com/whatcould/commitify/blob/master/main.py =D
def notify(email, text, title, link=None):
    params = {'text':text,'title':title}
    if link:
        params['link'] = link
    count = 0
    while True:
        try:
            return urlfetch.fetch('http://api.notify.io/v1/notify/%s?api_key=%s' % (hashlib.md5(email).hexdigest(), keys.api_key), method='POST', payload=urllib.urlencode(params))
        except urlfetch.DownloadError:
            count += 1
            logging.debug('DownloadError on fetch: %s, %s' % (email, title))
            if count == 3:
                raise

