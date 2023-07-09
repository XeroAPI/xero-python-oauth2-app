# xero-python-oauth2-app

This is a companion app with the code to perform OAuth 2.0 authentication and demonstrate how to interact with Xero API endpoints

**You'll be able to connect to a Xero Organisation and make real API calls - we recommend you connect to the Demo company.
Please use your Demo Company organisation for your testing.**
[Here](https://central.xero.com/s/article/Use-the-demo-company) is how to turn it on.

## Getting Started

### Prerequirements
* python3.5+ installed
* git installed

### Download the code
* Clone this repo to your local drive.

### Local installation
* Open terminal window and navigate to your `xero-python-oauth-app` local drive directory 
* Create new python virtual environment by running `python3 -m venv venv`
* Activate new virtual environment by running `source venv/bin/activate`
* Install project dependencies by running `pip install -r requirements.txt`

### Troubleshooting
If you see an error when installing the project dependencies that looks something like ...

```
Please make sure you have the correct access rights
and the repository exists.
fatal: clone of 'git@github.com:mitsuhiko/flask-sphinx-themes.git' into submodule path '/private/var/folders/7d/_bchn9r12pn79fr63p88nhv80000gn/T/pip-build-myovpzcq/Flask-Session/docs/_themes' failed
Failed to clone 'docs/_themes'. Retry scheduled
git@github.com: Permission denied (publickey).
```

Please check that your SSH keys are setup for your github profile?
https://github.com/settings/keys

We ran into some issues with the current version of Flask-Session and had to point to a specific commit and download that code into our project. But in order to do that your [SSH keys need to be config](https://docs.github.com/en/github/authenticating-to-github/connecting-to-github-with-ssh).

## Create a Xero App
To obtain your API keys, follow these steps and create a Xero app

* Create a [free Xero user account](https://www.xero.com/us/signup/api/) (if you don't have one)
* Login to [Xero developer center](https://developer.xero.com/myapps)
* Click "New App" link
* Enter your App name, company url, privacy policy url.
* Enter the redirect URI (your callback url - i.e. `http://localhost:5000/callback`)
    * Be aware `http://localhost/` and `http:/127.0.0.1/` are different urls
* Agree to terms and condition and click "Create App".
* Click "Generate a secret" button.
* Copy your client id and client secret and save for use later.
* Click the "Save" button. You secret is now hidden.

## Configure API keys
* Create a `config.py` file in the root directory of this project & add the 2 variables
```python
CLIENT_ID = "...client id string..."
CLIENT_SECRET = "...client secret string..."
STATE = "...my super secure state..."
```

Currently state is required. An empty string is not valid.

## Take it for a spin

* Make sure your python virtual environment activated `source venv/bin/activate`
* Install packages the app is dependent on `pip install -r requirements.txt`
* Start flask application `python3 app.py`
* Launch your browser and navigate to http://localhost:5000/login 
* You should be redirected to Xero login page.
* Grant access to your user account and select the Demo company to connect to.
* Done - try out the different API calls

### This app functions include:

* connect & reconnect to xero
* storing Xero token in a permanent flask session (in local drive file)
* refresh Xero access token on expiry  (happens automatically)
* read organisation information from /organisation endpoint
* read invoices information from /invoices endpoint
* create a new contact in Xero

## License

This software is published under the [MIT License](http://en.wikipedia.org/wiki/MIT_License).

	Copyright (c) 2020 Xero Limited

	Permission is hereby granted, free of charge, to any person
	obtaining a copy of this software and associated documentation
	files (the "Software"), to deal in the Software without
	restriction, including without limitation the rights to use,
	copy, modify, merge, publish, distribute, sublicense, and/or sell
	copies of the Software, and to permit persons to whom the
	Software is furnished to do so, subject to the following
	conditions:

	The above copyright notice and this permission notice shall be
	included in all copies or substantial portions of the Software.

	THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
	EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
	OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
	NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
	HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
	WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
	FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
	OTHER DEALINGS IN THE SOFTWARE.

