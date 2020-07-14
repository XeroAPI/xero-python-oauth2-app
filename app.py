# -*- coding: utf-8 -*-
import os
import time
import dateutil.parser
import re

from dateutil.parser import parse
from pathlib import Path
from random import seed
from random import randint
from functools import wraps
from io import BytesIO
from logging.config import dictConfig

from flask import Flask, url_for, render_template, session, redirect, json, send_file
from flask_oauthlib.contrib.client import OAuth, OAuth2Application
from flask_session import Session
from xero_python.accounting import AccountingApi, ContactPerson, Contact, Contacts, Account, Accounts, AccountType, Invoices, Invoice, LineItem
from xero_python.assets import AssetApi, Asset, AssetStatus, AssetStatusQueryParam, AssetType, BookDepreciationSetting
from xero_python.project import ProjectApi, Projects, ProjectCreateOrUpdate, ProjectPatch, ProjectStatus, ProjectUsers, TimeEntryCreateOrUpdate
from xero_python.payrollau import PayrollAuApi, Employees, Employee, EmployeeStatus,State, HomeAddress
from xero_python.api_client import ApiClient, serialize
from xero_python.api_client.configuration import Configuration
from xero_python.api_client.oauth2 import OAuth2Token
from xero_python.exceptions import AccountingBadRequestException
from xero_python.identity import IdentityApi
from xero_python.utils import getvalue

import logging_settings
from utils import jsonify, serialize_model

dictConfig(logging_settings.default_settings)

# configure main flask application
app = Flask(__name__)
app.config.from_object("default_settings")
app.config.from_pyfile("config.py", silent=True)

if app.config["ENV"] != "production":
    # allow oauth2 loop to run over http (used for local testing only)
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

# configure persistent session cache
Session(app)

# configure flask-oauthlib application
# TODO fetch config from https://identity.xero.com/.well-known/openid-configuration #1
oauth = OAuth(app)
xero = oauth.remote_app(
    name="xero",
    version="2",
    client_id=app.config["CLIENT_ID"],
    client_secret=app.config["CLIENT_SECRET"],
    endpoint_url="https://api.xero.com/",
    authorization_url="https://login.xero.com/identity/connect/authorize",
    access_token_url="https://identity.xero.com/connect/token",
    refresh_token_url="https://identity.xero.com/connect/token",
    scope="offline_access openid profile email accounting.transactions "
    "accounting.transactions.read accounting.reports.read "
    "accounting.journals.read accounting.settings accounting.settings.read "
    "accounting.contacts accounting.contacts.read accounting.attachments "
    "accounting.attachments.read assets projects "
    "payroll.employees payroll.payruns payroll.payslip payroll.timesheets payroll.settings",
)  # type: OAuth2Application


# configure xero-python sdk client
api_client = ApiClient(
    Configuration(
        debug=app.config["DEBUG"],
        oauth2_token=OAuth2Token(
            client_id=app.config["CLIENT_ID"], client_secret=app.config["CLIENT_SECRET"]
        ),
    ),
    pool_threads=1,
)

# configure token persistence and exchange point between flask-oauthlib and xero-python
@xero.tokengetter
@api_client.oauth2_token_getter
def obtain_xero_oauth2_token():
    return session.get("token")


@xero.tokensaver
@api_client.oauth2_token_saver
def store_xero_oauth2_token(token):
    session["token"] = token
    session.modified = True


def xero_token_required(function):
    @wraps(function)
    def decorator(*args, **kwargs):
        xero_token = obtain_xero_oauth2_token()
        if not xero_token:
            return redirect(url_for("login", _external=True))

        return function(*args, **kwargs)

    return decorator

def attachment_image():
    return Path(__file__).resolve().parent.joinpath("helo-heros.jpg")

def get_code_snippet(endpoint,action):
    s = open("app.py").read()
    startstr = "["+ endpoint +":"+ action +"]"
    endstr = "#[/"+ endpoint +":"+ action +"]"
    start = s.find(startstr) + len(startstr)
    end = s.find(endstr)
    substring = "  accounting_api = AccountingApi(api_client) \n"
    substring = substring + s[start:end]
    substring = s[start:end]
    return substring

def get_random_num():
    return str(randint(0, 10000))

@app.route("/")
def index():
    xero_access = dict(obtain_xero_oauth2_token() or {})
    return render_template(
        "code.html",
        title="Home | oauth token",
        code=json.dumps(xero_access, sort_keys=True, indent=4),
    )


@app.route("/tenants")
@xero_token_required
def tenants():
    identity_api = IdentityApi(api_client)
    accounting_api = AccountingApi(api_client)
    asset_api = AssetApi(api_client)

    available_tenants = []
    for connection in identity_api.get_connections():
        tenant = serialize(connection)
        if connection.tenant_type == "ORGANISATION":
            organisations = accounting_api.get_organisations(
                xero_tenant_id=connection.tenant_id
            )
            tenant["organisations"] = serialize(organisations)

        available_tenants.append(tenant)

    return render_template(
        "output.html",
        title="Xero Tenants",
        code=json.dumps(available_tenants, sort_keys=True, indent=4),
        len=0
    )


@app.route("/create-contact-person")
@xero_token_required
def create_contact_person():
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)
    msgs = {}
    msgs['value'] = []

    contact_person = ContactPerson(
        first_name="John",
        last_name="Smith",
        email_address="john.smith@24locks.com",
        include_in_emails=True,
    )
    contact = Contact(
        name="FooBar",
        first_name="Foo",
        last_name="Bar",
        email_address="ben.bowden@24locks.com",
        contact_persons=[contact_person],
    )
    contacts = Contacts(contacts=[contact])
    try:
        created_contacts = accounting_api.create_contacts(
            xero_tenant_id, contacts=contacts
        )  # type: Contacts
    except AccountingBadRequestException as exception:
        sub_title = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "Contact {} created.".format(
            getvalue(created_contacts, "contacts.0.name", "")
        )
        msgs['value'].append(msg)
        #code = serialize_model(created_contacts)

    return render_template(
        "output.html",  title="Contacts : Create", code=code, msg=msgs['value'], len = len(msgs['value'])
    )

@app.route("/accounting_account_read_all")
@xero_token_required
def accounting_account_read_all():
    code = get_code_snippet("ACCOUNTS","READ_ALL")

    #[ACCOUNTS:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_accounts = accounting_api.get_accounts(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Accounts read {} total".format(
            len(read_accounts.accounts)
        )
        json = serialize_model(read_accounts)
    #[/ACCOUNTS:READ_ALL]
    
    return render_template(
        "output.html", title="Accounts", code=code, json=json, output=output, len = 0
    )
    
@app.route("/accounting_account_read_one")
@xero_token_required
def accounting_account_read_one():
    code = get_code_snippet("ACCOUNTS","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_accounts = accounting_api.get_accounts(
            xero_tenant_id
        ) 
        account_id = getvalue(read_accounts, "accounts.0.account_id", "");
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    
    #[ACCOUNTS:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)
    
    try:
        read_one_account = accounting_api.get_account(
            xero_tenant_id, account_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Account read with name {} ".format(
            getvalue(read_accounts, "accounts.0.name", "")
        )
        json = serialize_model(read_one_account)
    #[/ACCOUNTS:READ_ONE]

    return render_template(
        "output.html", title="Accounts", code=code, json=json, output=output, len = 0
    )

@app.route("/accounting_account_create")
@xero_token_required
def accounting_account_create():
    code = get_code_snippet("ACCOUNTS","CREATE")
    #[ACCOUNTS:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)
    
    account = Account(
        name="FooBar" + get_random_num(),
        code=get_random_num(),
        description="My Foobar",
        type=AccountType.EXPENSE,
    )
      
    try:
        created_accounts = accounting_api.create_account(
            xero_tenant_id, account=account
        )
        account_id = getvalue(created_accounts, "accounts.0.account_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Account created with name {} .".format(
            getvalue(created_accounts, "accounts.0.name", "")
        )
        json = serialize_model(created_accounts)
    #[/ACCOUNTS:CREATE]
 
    return render_template(
        "output.html", title="Accounts", code=code, output=output, json=json, len = 0
    )
    
@app.route("/accounting_account_update")
@xero_token_required
def accounting_account_update():
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # CREATE ACCOUNT
    account = Account(
        name="FooBar" + randNum,
        code=randNum,
        description="My Foobar",
        type=AccountType.EXPENSE,
    )
    accounts = Accounts(accounts=[account])
    try:
        created_accounts = accounting_api.create_account(
            xero_tenant_id, account=account
        )   # type: Accounts
        account_id = getvalue(created_accounts, "accounts.0.account_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)

    #[ACCOUNTS:UPDATE]
    account = Account(
        description="Update me",
    )
    
    try:
        created_accounts = accounting_api.update_account(
            xero_tenant_id, account_id, account
        )
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "Account updated description to '{}' updated.".format(
            getvalue(created_accounts, "accounts.0.description", "")
        )
    #[/ACCOUNTS:UPDATE]
        code = get_code_snippet("ACCOUNTS","UPDATE")
        msgs['value'].append(msg)
    
    return render_template(
        "output.html", title="Accounts", code=code, msg=msgs['value'], len = len(msgs['value'])
    )

@app.route("/accounting_account_create_attachment")
@xero_token_required
def accounting_account_create_attachment():
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # CREATE ACCOUNT
    account = Account(
        name="FooBar" + randNum,
        code=randNum,
        description="My Foobar",
        type=AccountType.EXPENSE,
    )
    accounts = Accounts(accounts=[account])
    try:
        created_accounts = accounting_api.create_account(
            xero_tenant_id, account=account
        )   # type: Accounts
        account_id = getvalue(created_accounts, "accounts.0.account_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)

    # CREATE ACCOUNT ATTACHMENT
    
    # READ ALL ACCOUNTS
    try:
        where = "Status==\"ACTIVE\"";
        read_accounts = accounting_api.get_accounts(
            xero_tenant_id,
            where=where
        )  # type: Accounts
        attachment_account_id = getvalue(created_accounts, "accounts.0.account_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        try: 
            include_online = True
            myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
            with myimage.open("rb") as image:
                account_attachment_created = accounting_api.create_account_attachment_by_file_name(
                    xero_tenant_id,
                    attachment_account_id,
                    file_name=myimage.name,
                    body=image.read(),
                )  # type: Attachments
        except AccountingBadRequestException as exception:
            msg = "Error: " + exception.reason
            code = jsonify(exception.error_data)
        else:
            msg = "Attachment url '{}' created.".format(
                getvalue(account_attachment_created, "attachments.0.url", "")
            )
            msgs['value'].append(msg)
            #code = serialize_model(account_attachment_created)
    
    return render_template(
        "output.html", title="Accounts", code=code, msg=msgs['value'], len = len(msgs['value'])
    )

@app.route("/accounting_account_archive")
@xero_token_required
def accounting_account_archive():
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # CREATE ACCOUNT
    account = Account(
        name="FooBar" + randNum,
        code=randNum,
        description="My Foobar",
        type=AccountType.EXPENSE,
    )
    accounts = Accounts(accounts=[account])
    try:
        created_accounts = accounting_api.create_account(
            xero_tenant_id, account=account
        )   # type: Accounts
        account_id = getvalue(created_accounts, "accounts.0.account_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)

    # ARCHIVE ACCOUNT
    accountUp = Account(
        status="ARCHIVED",
    )
    accountsUp = Accounts(accounts=[accountUp])
    try:
        created_accounts = accounting_api.update_account(
            xero_tenant_id, account_id, accountsUp
        )  
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "Account status '{}' archived.".format(
            getvalue(created_accounts, "accounts.0.status", "")
        )
        msgs['value'].append(msg)
        
    return render_template(
        "output.html", title="Accounts", code=code, msg=msgs['value'], len = len(msgs['value'])
    )

@app.route("/accounting_account_delete")
@xero_token_required
def accounting_account_delete():
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # CREATE ACCOUNT
    account = Account(
        name="FooBar" + randNum,
        code=randNum,
        description="My Foobar",
        type=AccountType.EXPENSE,
    )
    accounts = Accounts(accounts=[account])
    try:
        created_accounts = accounting_api.create_account(
            xero_tenant_id, account=account
        )   # type: Accounts
        account_id = getvalue(created_accounts, "accounts.0.account_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)

    # DELETE ACCOUNT
    try:
        created_accounts = accounting_api.delete_account(
            xero_tenant_id, account_id
        ) #204 empty response
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "Account deleted."
        msgs['value'].append(msg)
    
    return render_template(
        "output.html", title="Accounts", code=code, msg=msgs['value'], len = len(msgs['value'])
    )



@app.route("/invoices_read_all")
@xero_token_required
def invoices_read_all():
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    #[INVOICES:READ_ALL]
    invoices = accounting_api.get_invoices(
        xero_tenant_id, invoices
    )
    code = serialize_model(invoices)
    sub_title = "Total invoices found: {}".format(len(invoices.invoices))

    return render_template(
        "code.html", title="Invoices", code=code, sub_title=sub_title
    )
    
@app.route("/invoices_create")
@xero_token_required
def invoices_create():
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    code = get_code_snippet("INVOICES","CREATE")
    
    # READ CONTACT
    try:
        read_contacts = accounting_api.get_contacts(
            xero_tenant_id
        ) 
        contact_id = getvalue(read_contacts, "contacts.0.contact_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    
    # READ ACCOUNT
    where = "Type==\"SALES\"&&Status==\"ACTIVE\"";
    try:
        read_accounts = accounting_api.get_accounts(
            xero_tenant_id, where=where
        ) 
        account_id = getvalue(read_accounts, "accounts.0.account_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    
    #[INVOICES:CREATE]
    contact = Contact(
        contact_id=contact_id
    )
    
    line_item = LineItem(
        account_code=account_id,
        description= "Consulting",
        quantity=1.0,
        unit_amount=10.0,
    )
    
    invoice = Invoice(
        line_items=[line_item],
        contact=contact,
        due_date= dateutil.parser.parse("2020-09-03T00:00:00Z"),
        date= dateutil.parser.parse("2020-07-03T00:00:00Z"),
        type="ACCREC"
    )
    
    invoices = Invoices(invoices=[invoice])
    
    try:
        created_invoices = accounting_api.create_invoices(
            xero_tenant_id, invoices=invoices
        ) 
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:  
        output = "New invoices status is '{}'.".format(
            getvalue(created_invoices, "invoices.0.status", "")
        )
        json = serialize_model(created_invoices)
    #[/INVOICES:CREATE]
        
    return render_template(
        "output.html", title="Invoices", code=code, output=output, json=json, msg=msgs['value'], len = len(msgs['value'])
    )

@app.route("/assets_read_all")
@xero_token_required
def assets_read_all():
    xero_tenant_id = get_xero_tenant_id()
    asset_api = AssetApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # READ ASSETS
    try:
        read_assets = asset_api.get_assets(
            xero_tenant_id, status=AssetStatusQueryParam.DRAFT
        )  # type: Assets
        asset_id = getvalue(read_assets, "items.0.asset_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "Assets read first one purchase date {}.".format(
            getvalue(read_assets, "items.0.purchase_date", "")
        )
        msgs['value'].append(msg)
    
    return render_template(
        "output.html", title="Assets : Read (all)", code=code, msg=msgs['value'], len = len(msgs['value'])
    )
    
@app.route("/assets_read_one")
@xero_token_required
def assets_read_one():
    xero_tenant_id = get_xero_tenant_id()
    asset_api = AssetApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # READ ALL ASSETS
    try:
        read_assets = asset_api.get_assets(
            xero_tenant_id, status=AssetStatusQueryParam.DRAFT
        )  # type: Assets
        asset_id = getvalue(read_assets, "items.0.asset_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    
    # READ ASSET BY ID
    try:
        read_asset_by_id = asset_api.get_asset_by_id(
            xero_tenant_id, asset_id
        )  # type: Asset
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "Asset read with name {}.".format(
            getvalue(read_asset_by_id, "asset_name", "")
        )
        msgs['value'].append(msg)
    
    return render_template(
        "output.html", title="Assets : Read (one)", code=code, msg=msgs['value'], len = len(msgs['value'])
    )

@app.route("/assets_create")
@xero_token_required
def assets_create():
    xero_tenant_id = get_xero_tenant_id()
    asset_api = AssetApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # CREATE ASSETS
    asset = Asset(
        asset_number="123" + randNum,
        asset_name=randNum,
        asset_status=AssetStatus.DRAFT,
        disposal_price=20.00,
        purchase_price=100.0,
        accounting_book_value=99.50,
    )
    try:
        created_asset = asset_api.create_asset(
            xero_tenant_id, asset=asset
        )  # type: Assets
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "Asset created with name {}.".format(
            getvalue(created_asset, "asset_name", "")
        )
        msgs['value'].append(msg)
     
    return render_template(
        "output.html", title="Asset : Create", code=code, msg=msgs['value'], len = len(msgs['value'])
    )
    
@app.route("/asset_types_read_all")
@xero_token_required
def asset_types_read_all():
    xero_tenant_id = get_xero_tenant_id()
    asset_api = AssetApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # READ ASSET TYPES  
    try:
        read_asset_types = asset_api.get_asset_types(
            xero_tenant_id
        )  # type: Array of Assets
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "Assets Types read and first one name {}.".format(
            getvalue(read_asset_types, "0.asset_type_name", "")
        )
        msgs['value'].append(msg)
        
    return render_template(
        "output.html", title="Asset Type : Read (all)", code=code, msg=msgs['value'], len = len(msgs['value'])
    )
    
@app.route("/asset_types_create")
@xero_token_required
def asset_types_create():
    xero_tenant_id = get_xero_tenant_id()
    asset_api = AssetApi(api_client)
    accounting_api = AccountingApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # CREATE ASSET TYPE
    where = "Type==\"FIXED\"&&Status==\"ACTIVE\"";
    read_accounts_1 = accounting_api.get_accounts(
        xero_tenant_id,
        where=where
        )  # type: Accounts
    fixed_asset_account_id = getvalue(read_accounts_1, "accounts.0.account_id", "");
    
    where = "Type==\"EXPENSE\"&&Status==\"ACTIVE\"";
    read_accounts_2 = accounting_api.get_accounts(
        xero_tenant_id,
        where=where
        )  # type: Accounts
    depreciation_expense_account_id = getvalue(read_accounts_2, "accounts.0.account_id", "");
    
    where = "Type==\"DEPRECIATN\"&&Status==\"ACTIVE\"";
    read_accounts_3 = accounting_api.get_accounts(
        xero_tenant_id,
        where=where
        )  # type: Accounts
    accumulated_depreciation_account_id = getvalue(read_accounts_3, "accounts.0.account_id", "");

    book_depreciation_setting = BookDepreciationSetting(
        averaging_method="ActualDays",
        depreciation_calculation_method="None",
        depreciation_rate=10.00,
        depreciation_method="DiminishingValue100",
    )
    
    asset_type = AssetType(
        asset_type_name="ABC" + randNum,
        fixed_asset_account_id=fixed_asset_account_id,
        depreciation_expense_account_id=depreciation_expense_account_id,
        accumulated_depreciation_account_id=accumulated_depreciation_account_id,
        book_depreciation_setting=book_depreciation_setting,
    )
    try:
        created_asset_type = asset_api.create_asset_type(
            xero_tenant_id, asset_type=asset_type
        )  # type: Assets
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "Asset Type created with name {}.".format(
            getvalue(created_asset_type, "asset_type_name", "")
        )
        msgs['value'].append(msg)
        
    return render_template(
        "output.html", title="Asset Type : Create", code=code, msg=msgs['value'], len = len(msgs['value'])
    )
    
@app.route("/asset_settings_read")
@xero_token_required
def asset_settings_read():
    xero_tenant_id = get_xero_tenant_id()
    asset_api = AssetApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # READ ASSET SETTINGS  
    try:
        read_asset_settings = asset_api.get_asset_settings(
            xero_tenant_id
        )  # type: Settings
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "READ all Assets Settings, number {}.".format(
            getvalue(read_asset_settings, "asset_number_sequence", "")
        )
        msgs['value'].append(msg)
        
    return render_template(
        "output.html", title="Asset Settings : Read", code=code, msg=msgs['value'], len = len(msgs['value'])
    )
    
@app.route("/projects")
@xero_token_required
def projects():
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)
    accounting_api = AccountingApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # READ PROJECTS
    try:
        read_projects = project_api.get_projects(
            xero_tenant_id
        )  # type: Projects
        project_id = getvalue(read_projects, "items.0.project_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "READ all Projects - first one name {}.".format(
            getvalue(read_projects, "items.0.name", "")
        )
        msgs['value'].append(msg)
        
    # READ PROJECT
    try:
        read_project = project_api.get_project(
            xero_tenant_id, project_id=project_id
        )  # type: Project
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "READ one Project - name {}.".format(
            getvalue(read_project, "name", "")
        )
        msgs['value'].append(msg)
        
    # CREATE PROJECT
    # READ CONTACTS FIRST
    try:
        read_contacts = accounting_api.get_contacts(
            xero_tenant_id
        )  # type: Contacts
        contact_id = getvalue(read_contacts, "contacts.0.contact_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    
    project_create_or_update = ProjectCreateOrUpdate(
        contact_id=contact_id,
        name="Foobar",
        estimate_amount=10.00
    )
    try:
        created_project = project_api.create_project(
            xero_tenant_id, project_create_or_update=project_create_or_update
        )  # type: Project
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "CREATED Project - name {}.".format(
            getvalue(created_project, "name", "")
        )
        msgs['value'].append(msg)
        
    # UPDATE PROJECT
    project_create_or_update = ProjectCreateOrUpdate(
        name="BarFoo"
    )
    try:
        updated_project = project_api.update_project(
            xero_tenant_id, project_id=project_id, project_create_or_update=project_create_or_update
        )  # type: 204 no response
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "UPDATED Project"
        msgs['value'].append(msg)
        
    # PATCH PROJECT
    project_patch = ProjectPatch(
        status=ProjectStatus.INPROGRESS
    )
    try:
        patched_project = project_api.patch_project(
            xero_tenant_id, project_id=project_id, project_patch=project_patch
        )  # type: 204 no response
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "PATCHED Project"
        msgs['value'].append(msg)
    
    return render_template(
        "output.html", title="Accounts", code=code, msg=msgs['value'], len = len(msgs['value'])
    )
    
@app.route("/projects_read_all")
@xero_token_required
def projects_read_all():
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # READ PROJECTS
    try:
        read_projects = project_api.get_projects(
            xero_tenant_id
        )  # type: Projects
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "READ all Projects - first one name {}.".format(
            getvalue(read_projects, "items.0.name", "")
        )
        msgs['value'].append(msg)
        
    return render_template(
        "output.html", title="Accounts", code=code, msg=msgs['value'], len = len(msgs['value'])
    )

@app.route("/projects_read_one")
@xero_token_required
def projects_read_one():
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # READ PROJECTS
    try:
        read_projects = project_api.get_projects(
            xero_tenant_id
        )  # type: Projects
        project_id = getvalue(read_projects, "items.0.project_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
        
    # READ ONE PROJECT by ID
    try:
        read_project = project_api.get_project(
            xero_tenant_id, project_id=project_id
        )  # type: Project
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "READ one Project - name {}.".format(
            getvalue(read_project, "name", "")
        )
        msgs['value'].append(msg)
    
    return render_template(
        "output.html", title="Accounts", code=code, msg=msgs['value'], len = len(msgs['value'])
    )

@app.route("/projects_create")
@xero_token_required
def projects_create():
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)
    accounting_api = AccountingApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
        
    # CREATE PROJECT
    # READ CONTACTS FIRST
    try:
        read_contacts = accounting_api.get_contacts(
            xero_tenant_id
        )  # type: Contacts
        contact_id = getvalue(read_contacts, "contacts.0.contact_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    
    project_create_or_update = ProjectCreateOrUpdate(
        contact_id=contact_id,
        name="Foobar",
        estimate_amount=10.00
    )
    try:
        created_project = project_api.create_project(
            xero_tenant_id, project_create_or_update=project_create_or_update
        )  # type: Project
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "CREATED Project - name {}.".format(
            getvalue(created_project, "name", "")
        )
        msgs['value'].append(msg)
    
    return render_template(
        "output.html", title="Accounts", code=code, msg=msgs['value'], len = len(msgs['value'])
    )

@app.route("/projects_update")
@xero_token_required
def projects_update():
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)
    accounting_api = AccountingApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # READ PROJECTS
    try:
        read_projects = project_api.get_projects(
            xero_tenant_id
        )  # type: Projects
        project_id = getvalue(read_projects, "items.0.project_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
        
    # UPDATE PROJECT
    project_create_or_update = ProjectCreateOrUpdate(
        name="BarFoo"
    )
    try:
        updated_project = project_api.update_project(
            xero_tenant_id, project_id=project_id, project_create_or_update=project_create_or_update
        )  # type: 204 no response
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "Project update success"
        msgs['value'].append(msg)
    
    return render_template(
        "output.html", title="Accounts", code=code, msg=msgs['value'], len = len(msgs['value'])
    )

@app.route("/projects_patch")
@xero_token_required
def projects_patch():
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)
    accounting_api = AccountingApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # READ PROJECTS
    try:
        read_projects = project_api.get_projects(
            xero_tenant_id
        )  # type: Projects
        project_id = getvalue(read_projects, "items.0.project_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
        
    # PATCH PROJECT
    project_patch = ProjectPatch(
        status=ProjectStatus.INPROGRESS
    )
    try:
        patched_project = project_api.patch_project(
            xero_tenant_id, project_id=project_id, project_patch=project_patch
        )  # type: 204 no response
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "Project patch success"
        msgs['value'].append(msg)
    
    return render_template(
        "output.html", title="Accounts", code=code, msg=msgs['value'], len = len(msgs['value'])
    )

@app.route("/projectusers_read")
@xero_token_required
def projectusers_read():
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # READ PROJECT USERS
    try:
        read_project_users = project_api.get_project_users(
            xero_tenant_id
        )  # type: ProjectUsers
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "READ all Project Users - first one name {}.".format(
            getvalue(read_project_users, "items.0.name", "")
        )
        msgs['value'].append(msg)
        
    return render_template(
        "output.html", title="Accounts", code=code, msg=msgs['value'], len = len(msgs['value'])
    )

@app.route("/tasks_read_all")
@xero_token_required
def tasks_read_all():
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)
    accounting_api = AccountingApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # READ TASKS
    # READ PROJECTS
    try:
        read_projects = project_api.get_projects(
            xero_tenant_id
        )  # type: Projects
        project_id = getvalue(read_projects, "items.0.project_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    try:
        read_tasks = project_api.get_tasks(
            xero_tenant_id, project_id=project_id
        )  # type: Tasks
        task_id = getvalue(read_tasks, "items.0.task_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "READ all Tasks - first one name {}.".format(
            getvalue(read_tasks, "items.0.name", "")
        )
        msgs['value'].append(msg)
        
    return render_template(
        "output.html", title="Accounts", code=code, msg=msgs['value'], len = len(msgs['value'])
    )
    
@app.route("/tasks_read_one")
@xero_token_required
def tasks_read_one():
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)
    accounting_api = AccountingApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # READ TASKS
    # READ PROJECTS
    try:
        read_projects = project_api.get_projects(
            xero_tenant_id
        )  # type: Projects
        project_id = getvalue(read_projects, "items.0.project_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    try:
        read_tasks = project_api.get_tasks(
            xero_tenant_id, project_id=project_id
        )  # type: Tasks
        task_id = getvalue(read_tasks, "items.0.task_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
        
    # READ one TASK
    try:
        read_task = project_api.get_task(
            xero_tenant_id, project_id=project_id, task_id=task_id
        )  # type: Task
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "READ one Task -  name {}.".format(
            getvalue(read_task, "name", "")
        )
        msgs['value'].append(msg)
    
    return render_template(
        "output.html", title="Accounts", code=code, msg=msgs['value'], len = len(msgs['value'])
    )
    
@app.route("/time_read_all")
@xero_token_required
def time_read_all():
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)
    accounting_api = AccountingApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # READ TIME ENTRIES
    # READ PROJECTS
    try:
        read_projects = project_api.get_projects(
            xero_tenant_id
        )  # type: Projects
        project_id = getvalue(read_projects, "items.0.project_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    try:
        read_time_entries = project_api.get_time_entries(
            xero_tenant_id, project_id=project_id
        )  # type: TimeEntries
        time_entry_id = getvalue(read_time_entries, "items.0.time_entry_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "READ all Time Entries - first one description {}.".format(
            getvalue(read_time_entries, "items.0.description", "")
        )
        msgs['value'].append(msg)
        #code = serialize_model(read_time_entries)
        
    return render_template(
        "output.html", title="Accounts", code=code, msg=msgs['value'], len = len(msgs['value'])
    )

@app.route("/time_read_one")
@xero_token_required
def time_read_one():
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)
    accounting_api = AccountingApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # READ TIME ENTRIES
    # READ PROJECTS
    try:
        read_projects = project_api.get_projects(
            xero_tenant_id
        )  # type: Projects
        project_id = getvalue(read_projects, "items.0.project_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    try:
        read_time_entries = project_api.get_time_entries(
            xero_tenant_id, project_id=project_id
        )  # type: TimeEntries
        time_entry_id = getvalue(read_time_entries, "items.0.time_entry_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    
    # READ TIME ENTRY
    try:
        read_time_entry = project_api.get_time_entry(
            xero_tenant_id, project_id=project_id, time_entry_id=time_entry_id
        )  # type: TimeEntries
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "READ one Time Entry - description {}.".format(
            getvalue(read_time_entry, "description", "")
        )
        msgs['value'].append(msg)
            
    return render_template(
        "output.html", title="Accounts", code=code, msg=msgs['value'], len = len(msgs['value'])
    )

@app.route("/time_create")
@xero_token_required
def time_create():
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # READ TIME ENTRIES
    # READ PROJECTS
    try:
        read_projects = project_api.get_projects(
            xero_tenant_id
        )  # type: Projects
        project_id = getvalue(read_projects, "items.0.project_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)

    # CREATE TIME ENTRY ; createTimeEntry
    # READ PROJECT USERS
    try:
        read_project_users = project_api.get_project_users(
            xero_tenant_id
        )  # type: ProjectUsers
        project_user_id = getvalue(read_project_users, "items.0.user_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    # READ TASKS
    try:
        read_tasks = project_api.get_tasks(
            xero_tenant_id, project_id=project_id
        )  # type: Tasks
        task_id = getvalue(read_tasks, "items.0.task_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
        
    time_entry_create_or_update = TimeEntryCreateOrUpdate(
        task_id=task_id,
        user_id=project_user_id,
        duration=30,
        description="Foobar description",
        date_utc=  dateutil.parser.parse("2020-07-03T15:38:00Z")
    )
    try:
        create_time_entry = project_api.create_time_entry(
            xero_tenant_id, project_id=project_id, time_entry_create_or_update=time_entry_create_or_update
        )  # type: TimeEntries
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "CREATE Time Entry - description {}.".format(
            getvalue(create_time_entry, "description", "")
        )
        msgs['value'].append(msg)
        
    return render_template(
        "output.html", title="Accounts", code=code, msg=msgs['value'], len = len(msgs['value'])
    )

@app.route("/payroll_au_employees")
@xero_token_required
def payroll_au_employees():
    xero_tenant_id = get_xero_tenant_id()
    payrollau_api = PayrollAuApi(api_client)
    accounting_api = AccountingApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # READ PAYROLL AU EMPLOYEES
    try:
        read_employees = payrollau_api.get_employees(
            xero_tenant_id
        )  # type: Employees
        #project_id = getvalue(read_employees, "items.0.project_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "READ all Employees - first one name {}.".format(
            getvalue(read_employees, "employees.0.date_of_birth", "")
        )
        msgs['value'].append(msg)
    
    return render_template(
        "output.html", title="Employees", code=code, msg=msgs['value'], len = len(msgs['value'])
    )
    
@app.route("/payroll_au_employees_create")
@xero_token_required
def payroll_au_employees_create():
    xero_tenant_id = get_xero_tenant_id()
    payrollau_api = PayrollAuApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # CREATE PAYROLL AU EMPLOYEES
    home_address = HomeAddress(
        address_line1="101 Green St",
        city="Island Bay",
        region=State.NSW,
        country="AUSTRALIA",
        postal_code="6023",
    )
    
    employee = Employee(
        first_name="Sirius",
        last_name="Black",
        email="sirius.black@hogwarts.com",
        date_of_birth= dateutil.parser.parse("1984-07-03T00:00:00Z"),
        start_date=dateutil.parser.parse("2020-07-03T00:00:00Z"),
        gender="M",
        is_authorised_to_approve_leave="true",
        is_authorised_to_approve_timesheets="true",
        classification="Marketing",
        job_title="Intern",
        status=EmployeeStatus.ACTIVE,
        home_address=home_address
    )
    # Add the same contact twice - the first one will succeed, but the
    # second contact will fail with a validation error which we'll show.
    employees = [employee]
    try:
        create_employees = payrollau_api.create_employee(
            xero_tenant_id, employee=employees
        )  # type: Employees
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "Created - first one name {}.".format(
            getvalue(create_employees, "employees.0.date_of_birth", "")
        )
        msgs['value'].append(msg)
    
    return render_template(
        "output.html", title="Employees", code=code, msg=msgs['value'], len = len(msgs['value'])
    )
    
@app.route("/payroll_au_leave_application")
@xero_token_required
def payroll_au_leave_application():
    xero_tenant_id = get_xero_tenant_id()
    payrollau_api = PayrollAuApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # READ LEAVE APPLICATIONS AU EMPLOYEES
    try:
        read_leave_applications = payrollau_api.get_leave_applications(
            xero_tenant_id
        )  # type: LeaveApplications
        #project_id = getvalue(read_leave_application, "items.0.project_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "READ all leave applications - first one id {}.".format(
            getvalue(read_leave_applications, "leave_applications.0.leave_application_id", "")
        )
        msgs['value'].append(msg)
    
    return render_template(
        "output.html", title="Leave Applications", code=code, msg=msgs['value'], len = len(msgs['value'])
    )
    
@app.route("/payroll_au_pay_items")
@xero_token_required
def payroll_au_pay_items():
    xero_tenant_id = get_xero_tenant_id()
    payrollau_api = PayrollAuApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # READ PAY ITEMS AU EMPLOYEES
    try:
        read_pay_items = payrollau_api.get_pay_items(
            xero_tenant_id
        )  # type: PayItems
        #project_id = getvalue(read_pay_items, "items.0.project_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "READ all pay items - first payitem earnings rate name {}.".format(
            getvalue(read_pay_items, "pay_items.0.earnings_rates.0.name", "")
        )
        msgs['value'].append(msg)   
    return render_template(
        "output.html", title="Pay Items", code=code, msg=msgs['value'], len = len(msgs['value'])
    )
        
@app.route("/payroll_au_payroll_calendars")
@xero_token_required
def payroll_au_payroll_calendars():
    xero_tenant_id = get_xero_tenant_id()
    payrollau_api = PayrollAuApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # READ PAYROLL CALENDARS AU EMPLOYEES
    try:
        read_payroll_calendars = payrollau_api.get_payroll_calendars(
            xero_tenant_id
        )  # type: PayrollCalendars
        #project_id = getvalue(read_payroll_calendars, "items.0.project_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "READ all payroll calendars - first one name {}.".format(
            getvalue(read_payroll_calendars, "payroll_calendars.0.name", "")
        )
        msgs['value'].append(msg)
    
    return render_template(
        "output.html", title="Payroll Calendars", code=code, msg=msgs['value'], len = len(msgs['value'])
    )

@app.route("/payroll_au_pay_runs")
@xero_token_required
def payroll_au_pay_runs():
    xero_tenant_id = get_xero_tenant_id()
    payrollau_api = PayrollAuApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # READ PAY RUNS AU EMPLOYEES
    try:
        read_pay_runs = payrollau_api.get_pay_runs(
            xero_tenant_id
        )  # type: PayRuns
        #project_id = getvalue(read_pay_runs, "items.0.project_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "READ all pay runs - first one id {}.".format(
            getvalue(read_pay_runs, "pay_runs.0.pay_run_id", "")
        )
        msgs['value'].append(msg)
    
    return render_template(
        "output.html", title="PayRuns", code=code, msg=msgs['value'], len = len(msgs['value'])
    )
    
@app.route("/payroll_au_pay_slips")
@xero_token_required
def payroll_au_pay_slips():
    xero_tenant_id = get_xero_tenant_id()
    payrollau_api = PayrollAuApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # READ PAY SLIPS AU EMPLOYEES
    # READ PAY RUNS AU EMPLOYEES
    try:
        read_pay_runs = payrollau_api.get_pay_runs(
            xero_tenant_id
        )  # type: PayRuns
        pay_run_id = getvalue(read_pay_runs, "pay_runs.0.pay_run_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
        
    # READ PAY RUN AU EMPLOYEES
    try:
        read_pay_run = payrollau_api.get_pay_run(
            xero_tenant_id, pay_run_id=pay_run_id
        )  # type: PayRuns
        payslip_id = getvalue(read_pay_run, "pay_runs.0.payslips.0.payslip_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    
    try:
        read_pay_slip = payrollau_api.get_payslip(
            xero_tenant_id, payslip_id=payslip_id
        )  # type: PaySlipObject
        #project_id = getvalue(read_pay_slips, "items.0.project_id", "");
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "READ pay slip - first one name {}.".format(
            getvalue(read_pay_slip, "payslip.first_name", "")
        )
        msgs['value'].append(msg)
    
    return render_template(
        "output.html", title="PaySlips", code=code, msg=msgs['value'], len = len(msgs['value'])
    )

@app.route("/payroll_au_settings")
@xero_token_required
def payroll_au_settings():
    xero_tenant_id = get_xero_tenant_id()
    payrollau_api = PayrollAuApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # READ SETTINGS AU EMPLOYEES
    try:
        read_settings = payrollau_api.get_settings(
            xero_tenant_id
        )  # type: Settings
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "READ all Settings - first account name {}.".format(
            getvalue(read_settings, "settings.accounts.0.name", "")
        )
        msgs['value'].append(msg)
        #code = serialize_model(read_settings)
    
    return render_template(
        "output.html", title="Settings", code=code, msg=msgs['value'], len = len(msgs['value'])
    )

@app.route("/payroll_au_superfunds")
@xero_token_required
def payroll_au_superfunds():
    xero_tenant_id = get_xero_tenant_id()
    payrollau_api = PayrollAuApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # READ SUPERFUND AU EMPLOYEES
    try:
        read_superfund = payrollau_api.get_superfunds(
            xero_tenant_id
        )  # type: SuperFund
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "READ all SuperFund - first name {}.".format(
            getvalue(read_superfund, "super_funds.0.name", "")
        )
        msgs['value'].append(msg)
        #code = serialize_model(read_superfund)
    
    return render_template(
        "output.html", title="SuperFunds", code=code, msg=msgs['value'], len = len(msgs['value'])
    )

@app.route("/payroll_au_superfund_products")
@xero_token_required
def payroll_au_superfund_products():
    xero_tenant_id = get_xero_tenant_id()
    payrollau_api = PayrollAuApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # READ SUPERFUND PRODUCTS AU EMPLOYEES
    try:
        read_superfund_products = payrollau_api.get_superfund_products(
            xero_tenant_id, usi="16517650366001"
        )  # type: SuperFundProducts
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "READ all SuperFund Product - first ABN {}.".format(
            getvalue(read_superfund_products, "super_fund_products.0.abn", "")
        )
        msgs['value'].append(msg)
        #code = serialize_model(read_superfund_products)
    
    return render_template(
        "output.html", title="SuperFunds", code=code, msg=msgs['value'], len = len(msgs['value'])
    )

@app.route("/payroll_au_timesheets")
@xero_token_required
def payroll_au_timesheets():
    xero_tenant_id = get_xero_tenant_id()
    payrollau_api = PayrollAuApi(api_client)
    code = ""
    msgs = {}
    msgs['value'] = []
    randNum = str(randint(0, 10000))
    
    # READ TIMESHEETS AU EMPLOYEES
    try:
        read_timeshets = payrollau_api.get_timesheets(
            xero_tenant_id
        )  # type: Timesheets
    except AccountingBadRequestException as exception:
        msg = "Error: " + exception.reason
        code = jsonify(exception.error_data)
    else:
        msg = "READ all Timesheets - first employee id {}.".format(
            getvalue(read_timeshets, "timesheets.0.employee_id", "")
        )
        msgs['value'].append(msg)
        #code = serialize_model(read_timeshets)
    
    return render_template(
        "output.html", title="SuperFunds", code=code, msg=msgs['value'], len = len(msgs['value'])
    )

@app.route("/create-multiple-contacts")
@xero_token_required
def create_multiple_contacts():
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    contact = Contact(
        name="George Jetson",
        first_name="George",
        last_name="Jetson",
        email_address="george.jetson@aol.com",
    )
    # Add the same contact twice - the first one will succeed, but the
    # second contact will fail with a validation error which we'll show.
    contacts = Contacts(contacts=[contact, contact])
    try:
        created_contacts = accounting_api.create_contacts(
            xero_tenant_id, contacts=contacts, summarize_errors=False
        )  # type: Contacts
    except AccountingBadRequestException as exception:
        sub_title = "Error: " + exception.reason
        result_list = None
        code = jsonify(exception.error_data)
    else:
        sub_title = ""
        result_list = []
        for contact in created_contacts.contacts:
            if contact.has_validation_errors:
                error = getvalue(contact.validation_errors, "0.message", "")
                result_list.append("Error: {}".format(error))
            else:
                result_list.append("Contact {} created.".format(contact.name))

        code = serialize_model(created_contacts)

    return render_template(
        "code.html",
        title="Create Multiple Contacts",
        code=code,
        result_list=result_list,
        sub_title=sub_title,
    )


@app.route("/login")
def login():
    redirect_url = url_for("oauth_callback", _external=True)
    response = xero.authorize(callback_uri=redirect_url)
    return response


@app.route("/callback")
def oauth_callback():
    try:
        response = xero.authorized_response()
    except Exception as e:
        print(e)
        raise
    # todo validate state value
    if response is None or response.get("access_token") is None:
        return "Access denied: response=%s" % response
    store_xero_oauth2_token(response)
    return redirect(url_for("index", _external=True))


@app.route("/logout")
def logout():
    store_xero_oauth2_token(None)
    return redirect(url_for("index", _external=True))


@app.route("/export-token")
@xero_token_required
def export_token():
    token = obtain_xero_oauth2_token()
    buffer = BytesIO("token={!r}".format(token).encode("utf-8"))
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="x.python",
        as_attachment=True,
        attachment_filename="oauth2_token.py",
    )


@app.route("/refresh-token")
@xero_token_required
def refresh_token():
    xero_token = obtain_xero_oauth2_token()
    new_token = api_client.refresh_oauth2_token()
    return render_template(
        "code.html",
        title="Xero OAuth2 token",
        code=jsonify({"Old Token": xero_token, "New token": new_token}),
        sub_title="token refreshed",
    )


def get_xero_tenant_id():
    token = obtain_xero_oauth2_token()
    if not token:
        return None

    identity_api = IdentityApi(api_client)
    for connection in identity_api.get_connections():
        if connection.tenant_type == "ORGANISATION":
            return connection.tenant_id


if __name__ == "__main__":
    app.run()
