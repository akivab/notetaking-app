import webapp2
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.ext.webapp import template
from google.appengine.api import urlfetch
from google.appengine.ext import db
import json
import os, re, urllib, datetime, logging
from operator import itemgetter


CLIENT = '0XGXFUPMyq'
SECRET = 'FvvHZUIq3vg0U3WNW1eWVm6mrwOqKAjEn75kJgiPVgCx1IIS'
REDIRECT_URI = 'http://slc-app.appspot.com/register/'
REST_HOST = 'https://api.sandbox.slcedu.org/api/rest/v1/%s'
OAUTH_HOST = 'https://api.sandbox.slcedu.org/api/oauth/%s'
TOKEN_ENDPOINT = OAUTH_HOST % 'token'
AUTH_URI =OAUTH_HOST % 'authorize'
HOME = REST_HOST % 'home'
STUDENTS = REST_HOST % 'students'
STUDENT_DATA = STUDENTS + '/%s'
STUDENTS_POST = STUDENT_DATA + '/custom'
CHECK = 'https://api.sandbox.slcedu.org/api/rest/system/session/check'

class Note(db.Model):
  teacher = db.StringProperty()
  student = db.StringProperty()
  note = db.StringProperty()
  date = db.DateTimeProperty(auto_now_add=True)
  color = db.StringProperty()
  visibility = db.StringProperty()

class MainPage(webapp2.RequestHandler):
  TOKEN = None
  TEACHER=None
  NAME=None
  def get(self):
    if self.request.cookies.get('tk'):
      self.getSettings()
      if re.match('/addnote', self.request.path):
        self.addNote()
      elif re.match('/studentreport', self.request.path):
        self.getReport()
      else:
        self.getMain()
      return

    code = self.request.get("code")
    if not code:
      request_params = '?response_type=code&client_id=%s&redirect_uri=%s' % (CLIENT, urllib.quote_plus(REDIRECT_URI))
      self.redirect('%s%s' % (AUTH_URI, request_params))
      return
    
    url = '%s?client_id=%s&client_secret=%s&grant_type=authorization_code&redirect_uri=%s&code=%s' % (TOKEN_ENDPOINT, CLIENT, SECRET, REDIRECT_URI, code)
    obj = self.getJson(url)
    logging.info(str(obj)) 
    self.response.set_cookie('tk', obj['access_token'], max_age=3600, path='/')
    self.response.out.write("<script>window.location.href='/'</script>")

  def getSettings(self):
    self.TOKEN = self.request.cookies.get('tk')
    about = self.getJson(CHECK)
    if not  'full_name' in about:
      self.response.set_cookie('tk', '', max_age=1, path='/')
      self.response.out.write("<script>window.location.href='/'</script>")
      return
    self.TEACHER = about['external_id']
    self.NAME = about['full_name']

  def getMain(self):
    students = self.getAllStudents()
    path = os.path.join(os.path.dirname(__file__), 'index.html')
    self.response.out.write(template.render(path, {'teacher':self.NAME,'children':students}))

  def getReport(self, opt_sid=None):
    student_id = self.request.get('id') if not opt_sid else opt_sid
    notes = Note.gql("WHERE student=:1 order by date desc", student_id).fetch(100)
    student = self.getJson(STUDENT_DATA % student_id)
    if student:
      student_name = '%s %s' % (student['name']['firstName'], student['name']['lastSurname'])
    about = self.getStudentData(student_id)
    path = os.path.join(os.path.dirname(__file__), 'report.html')
    self.response.out.write(template.render(path, {'teacher':self.NAME,'student':student_name, 'notes':notes, 'about': str(about)}))
 
  def addNote(self):
    student_id = self.request.get('id')
    message = self.request.get('message')
    admin = self.request.get('admin')
    notify = self.request.get('notify')
    parents = self.request.get('parents')
    students = self.request.get('students')
    teacher = self.request.get('teacher')
    color = self.request.get('color')
    obj = self.getStudentData(student_id)
    try:
      body = obj['body']
      body = json.loads(body)
    except:
      body = []
    student_note = Note.gql("WHERE student=:1", student_id).get()
    k = 1
    visibility = 0
    for i in [admin, teacher, parents, students]:
      if i: visibility += k 
      k *= 2
    if not student_note:
      obj = self.getStudentEvents(student_id)
      if obj:
        for evt in obj:
          for e in evt['event']:
            Note(student=student_id, teacher=self.TEACHER, date=datetime.datetime.strptime(evt['date'], '%Y-%m-%d'), note=e,color='yellow', visibility='15').put()
    note = Note(student=student_id, teacher=self.TEACHER, note=message,color=color, visibility=str(visibility))
    note.put()
    body.append({'msg':message,'color':color,'time':str(datetime.datetime.now()),'visibility':str(visibility)})
    logging.info(str(self.setStudentData(student_id, body)))
    
    self.redirect('/studentreport?id=%s' % student_id) 
    
  def getJson(self, url, data=None, method=urlfetch.GET):
    headers  = {'Content-Type': 'application/vnd.slc+json', 'Accept': 'application/vnd.slc+json'}
    if self.TOKEN is not None:
      headers['Authorization'] = 'bearer %s' % self.TOKEN
    result = urlfetch.fetch(url=url, payload=data, method=method, headers=headers)
    try:
      return json.loads(result.content)
    except:
      return None

  def getStudentEvents(self, student_id):
    important = ['studentGradebookEntries', 'attendances']
    data = {}
    for i in important:
      url = '%s?studentId=%s' % ((REST_HOST % i), student_id)
      obj = self.getJson(url)
      for arg in obj:
        if 'dateFulfilled' in arg: date = arg['dateFulfilled']
        else:
          year = arg['schoolYearAttendance']
          for yr in year:
            for evt in yr['attendanceEvent']:
              if evt['event'] != 'In Attendance':
                if not evt['date'] in data: data[evt['date']] = []
                data[evt['date']] += [evt['event']] 
          continue
        if not 'letterGradeEarned' in arg: continue
        if not date in data: data[date] = []
        data[date] += [arg['letterGradeEarned']]
    toret = []
    for i in sorted(data):
      toret.append({'date': i, 'event': data[i]})
    return toret

  def getStudentData(self, student_id):
    url = STUDENTS_POST % student_id
    student_data = self.getJson(STUDENT_DATA % student_id)
    return self.getJson(url)

  def setStudentData(self, student_id, data):
    url = STUDENTS_POST % student_id
    data = json.dumps({'body':json.dumps(data)})
    return self.getJson(url, data, urlfetch.PUT)

  def getStudents(self):
    students = self.getJson(REST_HOST % 'students')
#    sections = ','.join(i['id'] for i in sectionJson)
 #   url = REST_HOST % ('sections/%s/studentSectionAssociations/students' % sections)
#    students = self.getJson(url)
    return students

  def getAllStudents(self):
    peeps = {}
    students = self.getStudents() 
    for j in students:
      peeps[j['id']] = ('%s %s' % (j['name']['firstName'], j['name']['lastSurname']), j['sex'])
    return [{'id':j, 'name':peeps[j][0], 'sex':peeps[j][1]} for j in peeps]

application = webapp2.WSGIApplication(
    [('/.*', MainPage)], debug=False)

def main():
  run_wsgi_app(application)

if __name__ == "__main__":
  main()
