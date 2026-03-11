from flask import Flask, render_template, session, redirect, url_for, request
from flask_sqlalchemy import SQLAlchemy
from flask_bootstrap import Bootstrap
from flask_wtf import FlaskForm

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///data.sqlite3'
app.config['SECRET_KEY'] = 'password'
bootstrap = Bootstrap(app)
db = SQLAlchemy(app)

# Here is where we will take the data from the database
# The 'userscore' variable will be changed to be specific what the user has but for now I just put in dummy values
data = [
    {"id": 1, "category": "uninterrupted", "userscore": 8, "icon": "doublebed.svg"},
    {"id": 2, "category": "restlessness", "userscore": 20, "icon": "closedeye.svg"},   
    {"id": 3, "category": "environment", "userscore": 3, "icon": "audiolines.svg"},
]

# user_name and user_overall_score are dummy values currently 
@app.route('/')
def homePage():
    return render_template('home.html', data=data, user_name="Name", user_overall_score="excellent")

# @app.route('/regenerise/<int:pageID>')
# def singleProductPage(pageID):
#     return render_template('newPage.html', data = data)

if __name__ == '__main__':
    app.run(debug=True)
