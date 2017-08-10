from flask import Flask, render_template, request, redirect,jsonify, url_for, flash
app = Flask(__name__)

from sqlalchemy import create_engine, asc
from sqlalchemy.orm import sessionmaker
from database_setup import Base, Restaurant, MenuItem, User

#new imports for OAuth
from flask import session as login_session
import random, string
# step 5 imports
from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError
import httplib2
import json
from flask import make_response
import requests

# declare my client ID by referencing the client secrets file
CLIENT_ID = json.loads(open('client_secrets.json', 'r').read())['web']['client_id']

APPLICATION_NAME = "Restaurant Menu App"
#Connect to Database and create database session
engine = create_engine('sqlite:///restaurantmenuwithusers.db')
Base.metadata.bind = engine

DBSession = sessionmaker(bind=engine)
session = DBSession()



#Create a state token to prevent request forgery.
#Store it in the session for later validation.
@app.route('/login')
def showLogin():
  state = ''.join(random.choice(string.ascii_uppercase + string.digits) for x in xrange(32))
  #session as login_session acts as a dict and we are creating the key value pair here
  login_session['state'] = state
  return render_template('login.html', STATE=state)

  # function that accepts post requests
@app.route('/gconnect', methods=['POST'])
def gconnect():
  # do the tokens match?
  if request.args.get('state') != login_session['state']:
    response = make_response(json.dumps('Invalid state parameter'),401)
    response.headers['Content-Type'] = 'application/json'
    return response
  # collect the code if the token doesnt fail comparison
  code = request.data
  # use the one time code and exchange it for a credentials object which will contain the access token for my server.
  try:
    # create the oauth flow object with the secret added.
    oauth_flow = flow_from_clientsecrets('client_secrets.json', scope='')
    # one time code flow my server will be sending off
    oauth_flow.redirect_uri = 'postmessage'
    # initiate the exchange with my server using the one time code as input
    credentials = oauth_flow.step2_exchange(code)
  # If an error occurs along the way then
  except FlowExchangeError:
    response = make_response(json.dumps('Failed to upgrade the authorization code.'), 401)
    response.headers['Content-Type'] = 'application/json'
    return response

  # check that the access token is valid.
  access_token = credentials.access_token
  # append to this url so the google api server can verify this is a valid token for use when sent.
  url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s' % access_token)
  # here we create a json get request containing the URL and access token.  store the result in a variable called result
  h = httplib2.Http()
  result = json.loads(h.request(url, 'GET')[1])

  # if there is an error with result abort
  if result.get('error') is not None:
    response = make_response(json.dumps(result.get('error')),500)
    response.headers['Content-Type'] = 'application/json'

  # Verify that the access token is used for the intended user.
  gplus_id = credentials.id_token['sub']
  if result['user_id'] != gplus_id:
    response = make_response(json.dumps("Token's user ID doesnt match given user ID."), 401)
    response.headers['Content-Type'] = 'application/json'
    return response

  # check to see if the user is already logged into the system
  stored_credentials = login_session.get('credentials')
  stored_gplus_id = login_session.get('gplus_id')
  if stored_credentials is not None and gplus_id == stored_gplus_id:
    response = make_response(json.dumps('Current user is already connected.'),200)
    response.headers['Content-Type'] = 'application/json'

  # Store the access token in the session for later use.
  login_session['provider'] = 'google'
  login_session['credentials'] = credentials
  login_session['gplus_id'] = gplus_id
  response = make_response(json.dumps('Successfully connected user.', 200))

  #Get user info
  userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
  params = {'access_token': credentials.access_token, 'alt': 'json'}
  answer = requests.get(userinfo_url, params=params)

  data = answer.json()
  # print data
  # store the user info in my login_session
  login_session['username'] = data['name']
  login_session['picture'] = data['picture']
  login_session['email'] = data['email']

  user_id = getUserID(login_session['email'])
  if not user_id:
    user_id = createUser(login_session)
  login_session['user_id'] = user_id

  output = ''
  output += '<h1>Welcome, '
  output += login_session['username']
  output += '!</h1>'
  output += '<img src="'
  output += login_session['picture']
  output += ' " style = "width: 300px; height: 300px; border-radius: 150px;-webkit-border-radius: 150px; -moz-border-radius: 150px;">'

  flash('you are now logged in as %s' %login_session['username'])
  return output

# disconnect - Revoke a current user's token and reset their login_session.
@app.route('/gdisconnect')
def gdisconnect():
  # only disconnect a connected user.
  credentials = login_session.get('credentials')
  if credentials is None:
    response = make_response(json.dumps('Current user not connected.'),401)
    response.headers['Content-Type'] = "applicaiton/json"
    return response
  # Execute HTTP GET request to revoke current token
  access_token = credentials.access_token
  url = 'https://accounts.google.com/o/oauth2/revoke?token=%s'%access_token
  h = httplib2.Http()
  result = h.request(url, "GET")[0]

  # when you get a 200 success response clear the session
  if result['status'] == '200':
    del login_session['credentials']
    del login_session['gplus_id']
    del login_session['username']
    del login_session['email']
    del login_session['picture']

    response = make_response(json.dumps('Successfully disconnected.'), 200)
    response.headers['Content-Type'] = 'application/json'
    return response
  else:
    response = make_response(json.dumps('Failed to revoke token for given user.'), 400)
    response.headers['Content-Type'] = 'application/json'
    return response



@app.route('/fbconnect', methods=['POST'])
def fbconnect():
  if request.args.get('state') != login_session['state']:
    response = make_response(json.dumps('Invalid state parameter.'), 401)
    response.headers['Content-Type'] = 'application/json'
    return response
  access_token = request.data

  # get a long live token from short live token
  app_id = json.loads(open('fb_client_secrets.json', 'r').read())['web']['app_id']
  app_secret = json.loads(open('fb_client_secrets.json', 'r').read())['web']['app_secret']
  url = 'https://graph.facebook.com/oauth/access_token?grant_type=fb_exchange_token&client_id=%s&client_secret=%s&fb_exchange_token=%s' % (app_id, app_secret, access_token)
  h = httplib2.Http()
  result = h.request(url, 'GET')[1]

  # use token to get user info from the API
  userinfo_url = 'https://graph.facebook.com/v2.2/me'
  # strip expire tag from access token
  token = result.split('&')[0]

  url = 'https://graph.facebook.com/v2.8/me?%s&fields=name,id,email' % token
  h = httplib2.Http()
  result = h.request(url, 'GET')[1]

  data = json.loads(result)

  login_session['provider'] = 'facebook'
  login_session['username'] = data['name']
  login_session['email'] = data['email']
  login_session['facebook_id'] = data['id']


  # facebook uses separate api call for pic
  url = 'https://graph.facebook.com/v2.2/me/picture?%s&redirect=0&height=200&width=200' % token
  h = httplib2.Http()
  result = h.request(url, 'GET')[1]
  data = json.loads(result)
  login_session['picture'] = data['data']['url']

  # see if user exists
  user_id = getUserID(login_session['email'])
  if not user_id:
    user_id = CreateUser(login_session)
  login_Session['user_id'] = user_id

  output = ''
  output += '<h1>Welcome, '
  output += login_session['username']
  output += '!</h1>'
  output += '<img src="'
  output += login_session['picture']
  output += ' " style = "width: 300px; height: 300px; border-radius: 150px;-webkit-border-radius: 150px; -moz-border-radius: 150px;">'

  flash('Now logged in as %s' % login_session['username'])
  return output

@app.route('/fbdisconnect')
def fbdisconnect():
  facebook_id = login_session['facebook_id']
  url = 'https://graph.facebook.com/%s/permissions' % facebook_id
  h = httplib2.Http()
  result = h.request(url, 'DELETE')[1]
  del login_session['username']
  del login_session['email']
  del login_session['picture']
  del login_session['user_id']
  del login_session['facebook_id']
  return "you have been logged out"



@app.route('/disconnect')
def disconnect():
  if 'provider' in login_session:
    if login_session['provider'] == 'google':
      gdisconnect()
      del login_session['gplus_id']
      del login_session['credentials']
    if login_session['provider'] == 'facebook':
      fbdisconnect()
      del login_session['facebook_id']
    del login_session['username']
    del login_session['email']
    del login_session['picture']
    del login_session['user_id']
    del login_session['provider']
    flash("you have successfully been logged out")
    return redirect(url_for('showRestaurants'))
  else:
    flash("You were not logged in to begin with")
    redirect(url_for('showRestaurants'))



#JSON APIs to view Restaurant Information
@app.route('/restaurant/<int:restaurant_id>/menu/JSON')
def restaurantMenuJSON(restaurant_id):
    restaurant = session.query(Restaurant).filter_by(id = restaurant_id).one()
    items = session.query(MenuItem).filter_by(restaurant_id = restaurant_id).all()
    return jsonify(MenuItems=[i.serialize for i in items])


@app.route('/restaurant/<int:restaurant_id>/menu/<int:menu_id>/JSON')
def menuItemJSON(restaurant_id, menu_id):
    Menu_Item = session.query(MenuItem).filter_by(id = menu_id).one()
    return jsonify(Menu_Item = Menu_Item.serialize)

@app.route('/restaurant/JSON')
def restaurantsJSON():
    restaurants = session.query(Restaurant).all()
    return jsonify(restaurants= [r.serialize for r in restaurants])


#Show all restaurants
@app.route('/')
@app.route('/restaurant/')
def showRestaurants():
  restaurants = session.query(Restaurant).order_by(asc(Restaurant.name))
  if 'username' not in login_session:
    return render_template('publicrestaurants.html', restaurants=restaurants)
  else:
    return render_template('restaurants.html', restaurants=restaurants)

#Create a new restaurant
@app.route('/restaurant/new/', methods=['GET','POST'])
def newRestaurant():
  if 'username' not in login_session:
    return redirect('/login')
  if request.method == 'POST':
      newRestaurant = Restaurant(name = request.form['name'], user_id=login_session['user_id'])
      session.add(newRestaurant)
      flash('New Restaurant %s Successfully Created' % newRestaurant.name)
      session.commit()
      return redirect(url_for('showRestaurants'))
  else:
      return render_template('newRestaurant.html')

#Edit a restaurant
@app.route('/restaurant/<int:restaurant_id>/edit/', methods = ['GET', 'POST'])
def editRestaurant(restaurant_id):
  if 'username' not in login_session:
    return redirect('/login')
  editedRestaurant = session.query(Restaurant).filter_by(id = restaurant_id).one()
  if request.method == 'POST':
      if request.form['name']:
        editedRestaurant.name = request.form['name']
        flash('Restaurant Successfully Edited %s' % editedRestaurant.name)
        return redirect(url_for('showRestaurants'))
  else:
    return render_template('editRestaurant.html', restaurant = editedRestaurant)


#Delete a restaurant
@app.route('/restaurant/<int:restaurant_id>/delete/', methods = ['GET','POST'])
def deleteRestaurant(restaurant_id):
  if 'username' not in login_session:
    return redirect('/login')
  restaurantToDelete = session.query(Restaurant).filter_by(id = restaurant_id).one()
  if request.method == 'POST':
    session.delete(restaurantToDelete)
    flash('%s Successfully Deleted' % restaurantToDelete.name)
    session.commit()
    return redirect(url_for('showRestaurants', restaurant_id = restaurant_id))
  else:
    return render_template('deleteRestaurant.html',restaurant = restaurantToDelete)

#Show a restaurant menu
@app.route('/restaurant/<int:restaurant_id>/')
@app.route('/restaurant/<int:restaurant_id>/menu/')
def showMenu(restaurant_id):

  restaurant = session.query(Restaurant).filter_by(id = restaurant_id).one()

  creator = getUserInfo(restaurant.user_id)
  items = session.query(MenuItem).filter_by(restaurant_id = restaurant_id).all()

  # choose whether its a public user or private user
  if 'username' not in login_session or creator.id != login_session['user_id']:
    return render_template('publicmenu.html', items=items, restaurant=restaurant, creator=creator)
  else:
    return render_template('menu.html', items=items, restaurant=restaurant, creator=creator)



#Create a new menu item
@app.route('/restaurant/<int:restaurant_id>/menu/new/',methods=['GET','POST'])
def newMenuItem(restaurant_id):
  if 'username' not in login_session:
    return redirect('/login')
  restaurant = session.query(Restaurant).filter_by(id = restaurant_id).one()
  if request.method == 'POST':
      newItem = MenuItem(name = request.form['name'], description = request.form['description'], price = request.form['price'], course = request.form['course'], restaurant_id = restaurant_id, user_id = login_session['user_id'])
      session.add(newItem)
      session.commit()
      flash('New Menu %s Item Successfully Created' % (newItem.name))
      return redirect(url_for('showMenu', restaurant_id = restaurant_id))
  else:
      return render_template('newmenuitem.html', restaurant_id = restaurant_id)

#Edit a menu item
@app.route('/restaurant/<int:restaurant_id>/menu/<int:menu_id>/edit', methods=['GET','POST'])
def editMenuItem(restaurant_id, menu_id):
  if 'username' not in login_session:
    return redirect('/login')

  editedItem = session.query(MenuItem).filter_by(id = menu_id).one()
  restaurant = session.query(Restaurant).filter_by(id = restaurant_id).one()
  if request.method == 'POST':
      if request.form['name']:
          editedItem.name = request.form['name']
      if request.form['description']:
          editedItem.description = request.form['description']
      if request.form['price']:
          editedItem.price = request.form['price']
      if request.form['course']:
          editedItem.course = request.form['course']
      session.add(editedItem)
      session.commit()
      flash('Menu Item Successfully Edited')
      return redirect(url_for('showMenu', restaurant_id = restaurant_id))
  else:
      return render_template('editmenuitem.html', restaurant_id = restaurant_id, menu_id = menu_id, item = editedItem)


#Delete a menu item
@app.route('/restaurant/<int:restaurant_id>/menu/<int:menu_id>/delete', methods = ['GET','POST'])
def deleteMenuItem(restaurant_id,menu_id):
  if 'username' not in login_session:
    return redirect('/login')
  restaurant = session.query(Restaurant).filter_by(id = restaurant_id).one()
  itemToDelete = session.query(MenuItem).filter_by(id = menu_id).one()
  if request.method == 'POST':
      session.delete(itemToDelete)
      session.commit()
      flash('Menu Item Successfully Deleted')
      return redirect(url_for('showMenu', restaurant_id = restaurant_id))
  else:
      return render_template('deleteMenuItem.html', item = itemToDelete)

# takes an email address and returns an ID number if that email address belongs to a user stored in our database.
def getUserID(email):
  try:
    user = session.query(User).filter_by(email = email).one()
    return user.id
  except:
    return None


# if a user id is passed into this method it simply return s the user object associated with this ID number
def getUserInfo(user_id):
  user = session.query(User).filter_by(id=user_id).one()
  return user



# Im taking a login_sesion as input and creating a new user in our database, extracting all of the fields necessary
def createUser(login_session):
  newUser = User(name = login_session['username'], email = login_session['email'], picture = login_session['picture'])
  session.add(newUser)
  session.commit()
  user = session.query(User).filter_by(email = login_session['email']).one
  return user.id


if __name__ == '__main__':
  app.secret_key = 'super_secret_key'
  app.debug = True
  app.run(host = '0.0.0.0', port = 5000)
