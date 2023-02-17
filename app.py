# -*- coding: utf-8 -*-
import os
import time
import dateutil.parser
import datetime
import re
import mimetypes

from dateutil.parser import parse
from datetime import date
from pathlib import Path
from random import seed
from random import randint
from functools import wraps
from io import BytesIO
from logging.config import dictConfig

from flask import Flask, url_for, render_template, session, redirect, json, send_file, request
from flask_oauthlib.contrib.client import OAuth, OAuth2Application
from flask_session import Session
from xero_python.accounting import AccountingApi, Account, Accounts, AccountType, Allocation, Allocations, BatchPayment, BatchPayments, BankTransaction, BankTransactions, BankTransfer, BankTransfers, Contact, Contacts, ContactGroup, ContactGroups, ContactPerson, CreditNote, CreditNotes, Currency, Currencies, CurrencyCode, Employee, Employees, ExpenseClaim, ExpenseClaims, HistoryRecord, HistoryRecords, Invoice, Invoices, Item, Items, LineAmountTypes, LineItem, Payment, Payments, PaymentService, PaymentServices, Phone, Purchase, Quote, Quotes, Receipt, Receipts, RepeatingInvoice, RepeatingInvoices, Schedule, TaxComponent, TaxRate, TaxRates, TaxType, TrackingCategory, TrackingCategories, TrackingOption, TrackingOptions, User, Users
from xero_python.assets import AssetApi, Asset, AssetStatus, AssetStatusQueryParam, AssetType, BookDepreciationSetting
from xero_python.project import ProjectApi, Amount, ChargeType, Projects, ProjectCreateOrUpdate, ProjectPatch, ProjectStatus, ProjectUsers, Task, TaskCreateOrUpdate, TimeEntryCreateOrUpdate
from xero_python.payrollau import PayrollAuApi, Employees, Employee, EmployeeStatus,State, HomeAddress
from xero_python.payrolluk import PayrollUkApi, Employees, Employee, Address, Employment
from xero_python.payrollnz import PayrollNzApi, Employees, Employee, Address, Employment, EmployeeLeaveSetup
from xero_python.file import FilesApi
from xero_python.finance import FinanceApi
from xero_python.api_client import ApiClient, serialize
from xero_python.api_client.configuration import Configuration
from xero_python.api_client.oauth2 import OAuth2Token
from xero_python.exceptions import AccountingBadRequestException, PayrollUkBadRequestException
from xero_python.identity import IdentityApi
from xero_python.utils import getvalue

import logging_settings
from utils import jsonify, serialize_model

dictConfig(logging_settings.default_settings)

# configure main flask application
app = Flask(__name__)
app.config.from_object("default_settings")
app.config.from_pyfile("config.py", silent=True)
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

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
    "files "
    "payroll.employees payroll.payruns payroll.payslip payroll.timesheets payroll.settings",
    # "paymentservices "
    # "finance.bankstatementsplus.read finance.cashvalidation.read finance.statements.read finance.accountingactivity.read",
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
    substring = s[start:end]
    return substring

def get_random_num():
    return str(randint(0, 10000))

@app.route("/")
def index():
    xero_access = dict(obtain_xero_oauth2_token() or {})
    return render_template(
        "output.html",
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

# ACCOUNTS
# getAccounts x
# createAccount x
# getAccount x
# updateAccount x
# deleteAccount x
# getAccountAttachments x
# getAccountAttachmentById x
# getAccountAttachmentByFileName x
# updateAccountAttachmentByFileName x
# createAccountAttachmentByFileName x

@app.route("/accounting_account_read_all")
@xero_token_required
def accounting_account_read_all():
    code = get_code_snippet("ACCOUNTS","READ_ALL")

    #[ACCOUNTS:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)
    order = 'Name ASC'

    try:
        read_accounts = accounting_api.get_accounts(
            xero_tenant_id, order
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
        "output.html", title="Accounts", code=code, json=json, output=output, len = 0, set="accounting", endpoint="account", action="read_all"
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
        account_id = getvalue(read_accounts, "accounts.0.account_id", "")
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
        "output.html", title="Accounts", code=code, json=json, output=output, len = 0, set="accounting", endpoint="account", action="read_one"
    )

@app.route("/accounting_account_get_attachments")
@xero_token_required
def accounting_account_get_attachments():
    code = get_code_snippet("ACCOUNTS","GET_ATTACHMENTS")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    # CREATE ACCOUNT
    account = Account(
        name="FooBar" + get_random_num(),
        code=get_random_num(),
        description="My Foobar",
        type=AccountType.EXPENSE,
    )

    try:
        created_accounts = accounting_api.create_account(
            xero_tenant_id, account
        )
        account_id = getvalue(created_accounts, "accounts.0.account_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        try:
            include_online = True
            file_name = "helo-heros.jpg"
            path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
            open_file = open(path_to_upload, 'rb')
            body = open_file.read()
            content_type = mimetypes.MimeTypes().guess_type(file_name)[0]
            account_attachment_created = accounting_api.create_account_attachment_by_file_name(
                xero_tenant_id,
                account_id,
                file_name,
                body,
            )
        except AccountingBadRequestException as exception:
            output = "Error: " + exception.reason
            json = jsonify(exception.error_data)

    # GET ACCOUNT ATTACHMENTS
    #[ACCOUNTS:GET_ATTACHMENTS]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_account_attachments = accounting_api.get_account_attachments(
            xero_tenant_id, account_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Account attachments read {} total".format(
            len(read_account_attachments.attachments)
        )
        json = serialize_model(read_account_attachments)
    #[/ACCOUNTS:GET_ATTACHMENTS]

    return render_template(
        "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="get_attachments"
    )

@app.route("/accounting_account_get_attachment_by_id")
@xero_token_required
def accounting_account_get_attachment_by_id():
    code = get_code_snippet("ACCOUNTS","GET_ATTACHMENTS_BY_ID")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    # CREATE ACCOUNT
    account = Account(
        name="FooBar" + get_random_num(),
        code=get_random_num(),
        description="My Foobar",
        type=AccountType.EXPENSE,
    )

    try:
        created_accounts = accounting_api.create_account(
            xero_tenant_id, account
        )
        account_id = getvalue(created_accounts, "accounts.0.account_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        try:
            include_online = True
            file_name = "helo-heros.jpg"
            path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
            open_file = open(path_to_upload, 'rb')
            body = open_file.read()
            content_type = mimetypes.MimeTypes().guess_type(file_name)[0]
            account_attachment_created = accounting_api.create_account_attachment_by_file_name(
                xero_tenant_id,
                account_id,
                file_name,
                body,
            )
            attachment_id = getvalue(account_attachment_created, "attachments.0.attachment_id", "")
        except AccountingBadRequestException as exception:
            output = "Error: " + exception.reason
            json = jsonify(exception.error_data)

    # GET ACCOUNT ATTACHMENTS
    #[ACCOUNTS:GET_ATTACHMENTS_BY_ID]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_account_attachments = accounting_api.get_account_attachment_by_id(
            xero_tenant_id, account_id, attachment_id, content_type
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Account attachment read with ID {} ".format(
            getvalue(read_account_attachments, "attachments.0.attachment_id", "")
        )
        json = serialize_model(read_account_attachments)
    #[/ACCOUNTS:GET_ATTACHMENTS_BY_ID]

    return render_template(
        "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="get_attachment_by_id"
    )

@app.route("/accounting_account_get_attachment_by_file_name")
@xero_token_required
def accounting_account_get_attachment_by_file_name():
    code = get_code_snippet("ACCOUNTS","GET_ATTACHMENT_BY_FILE_NAME")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    # CREATE ACCOUNT
    account = Account(
        name="FooBar" + get_random_num(),
        code=get_random_num(),
        description="My Foobar",
        type=AccountType.EXPENSE,
    )

    try:
        created_accounts = accounting_api.create_account(
            xero_tenant_id, account
        )
        account_id = getvalue(created_accounts, "accounts.0.account_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        try:
            include_online = True
            file_name = "helo-heros.jpg"
            path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
            open_file = open(path_to_upload, 'rb')
            body = open_file.read()
            content_type = mimetypes.MimeTypes().guess_type(file_name)[0]
            account_attachment_created = accounting_api.create_account_attachment_by_file_name(
                xero_tenant_id,
                account_id,
                file_name,
                body,
            )
            file_name = getvalue(account_attachment_created, "attachments.0.file_name", "")
        except AccountingBadRequestException as exception:
            output = "Error: " + exception.reason
            json = jsonify(exception.error_data)

    # GET ACCOUNT ATTACHMENTS
    #[ACCOUNTS:GET_ATTACHMENT_BY_FILE_NAME]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_account_attachments = accounting_api.get_account_attachment_by_file_name(
            xero_tenant_id, account_id, file_name, content_type
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Account attachment read with file name {} ".format(
            getvalue(read_account_attachments, "attachments.0.file_name", "")
        )
        json = serialize_model(read_account_attachments)
    #[/ACCOUNTS:GET_ATTACHMENT_BY_FILE_NAME]

    return render_template(
        "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="get_attachment_by_file_name"
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
            xero_tenant_id, account
        )
        account_id = getvalue(created_accounts, "accounts.0.account_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Account created with name {} .".format(
            getvalue(created_accounts, "accounts.0.name", "")
        )
        json = serialize_model(created_accounts)
    #[/ACCOUNTS:CREATE]

    return render_template(
        "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="create"
    )

@app.route("/accounting_account_update")
@xero_token_required
def accounting_account_update():
    code = get_code_snippet("ACCOUNTS","UPDATE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    # CREATE ACCOUNT
    account = Account(
        name="FooBar" + get_random_num(),
        code=get_random_num(),
        description="My Foobar",
        type=AccountType.EXPENSE,
    )

    try:
        created_accounts = accounting_api.create_account(
            xero_tenant_id, account
        )
        account_id = getvalue(created_accounts, "accounts.0.account_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[ACCOUNTS:UPDATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    account = Account(
        description="Update me",
    )

    accounts = Accounts(accounts=[account])

    try:
        updated_accounts = accounting_api.update_account(
            xero_tenant_id, account_id, accounts
        ) # type: Accounts
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Account updated description to '{}' updated.".format(
            getvalue(updated_accounts, "accounts.0.description", "")
        )
        json = serialize_model(updated_accounts)
    #[/ACCOUNTS:UPDATE]

    return render_template(
        "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="update"
    )

@app.route("/accounting_account_create_attachment")
@xero_token_required
def accounting_account_create_attachment():
    code = get_code_snippet("ACCOUNTS","CREATE_ATTACHMENT")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    # CREATE ACCOUNT
    account = Account(
        name="FooBar" + get_random_num(),
        code=get_random_num(),
        description="My Foobar",
        type=AccountType.EXPENSE,
    )

    try:
        created_accounts = accounting_api.create_account(
            xero_tenant_id, account
        )
        account_id = getvalue(created_accounts, "accounts.0.account_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    # CREATE ACCOUNT ATTACHMENT
    #[ACCOUNTS:CREATE_ATTACHMENT]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        include_online = True
        file_name = "helo-heros.jpg"
        path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
        open_file = open(path_to_upload, 'rb')
        body = open_file.read()
        content_type = mimetypes.MimeTypes().guess_type(file_name)[0]
        account_attachment_created = accounting_api.create_account_attachment_by_file_name(
            xero_tenant_id,
            account_id,
            file_name,
            body,
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Attachment url '{}' created.".format(
            getvalue(account_attachment_created, "attachments.0.url", "")
        )
        json = serialize_model(account_attachment_created)
    #[/ACCOUNTS:CREATE_ATTACHMENT]

    return render_template(
        "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="create_attachment"
    )

@app.route("/accounting_account_update_attachment")
@xero_token_required
def accounting_account_update_attachment():
    code = get_code_snippet("ACCOUNTS","UPDATE_ATTACHMENT")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    # CREATE ACCOUNT
    account = Account(
        name="FooBar" + get_random_num(),
        code=get_random_num(),
        description="My Foobar",
        type=AccountType.EXPENSE,
    )

    try:
        created_accounts = accounting_api.create_account(
            xero_tenant_id, account
        )
        account_id = getvalue(created_accounts, "accounts.0.account_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        try:
            include_online = True
            file_name = "helo-heros.jpg"
            path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
            open_file = open(path_to_upload, 'rb')
            body = open_file.read()
            content_type = mimetypes.MimeTypes().guess_type(file_name)[0]
            account_attachment_created = accounting_api.create_account_attachment_by_file_name(
                xero_tenant_id,
                account_id,
                file_name,
                body,
            )
            file_name = getvalue(account_attachment_created, "attachments.0.file_name", "")
        except AccountingBadRequestException as exception:
            output = "Error: " + exception.reason
            json = jsonify(exception.error_data)

    # UPDATE ACCOUNT ATTACHMENT
    #[ACCOUNTS:UPDATE_ATTACHMENT]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        include_online = True
        file_name = file_name
        path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
        open_file = open(path_to_upload, 'rb')
        body = open_file.read()
        content_type = mimetypes.MimeTypes().guess_type(file_name)[0]
        account_attachment_updated = accounting_api.update_account_attachment_by_file_name(
            xero_tenant_id,
            account_id,
            file_name,
            body,
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Attachment name '{}' updated.".format(
            getvalue(account_attachment_updated, "attachments.0.file_name", "")
        )
        json = serialize_model(account_attachment_updated)
    #[/ACCOUNTS:UPDATE_ATTACHMENT]

    return render_template(
        "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="update_attachment"
    )

@app.route("/accounting_account_archive")
@xero_token_required
def accounting_account_archive():
    code = get_code_snippet("ACCOUNTS","ARCHIVE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    # CREATE ACCOUNT
    account = Account(
        name="FooBar" + get_random_num(),
        code=get_random_num(),
        description="My Foobar",
        type=AccountType.EXPENSE,
    )

    try:
        created_accounts = accounting_api.create_account(
            xero_tenant_id, account
        )
        account_id = getvalue(created_accounts, "accounts.0.account_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[ACCOUNTS:ARCHIVE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    accountUp = Account(
        status="ARCHIVED",
    )

    accounts = Accounts(accounts=[accountUp])

    try:
        archived_accounts = accounting_api.update_account(
            xero_tenant_id, account_id, accounts
        ) # type: Accounts
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Account status {}".format(
            getvalue(archived_accounts, "accounts.0.status", "")
        )
        json = serialize_model(archived_accounts)
    #[/ACCOUNTS:ARCHIVE]

    return render_template(
        "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="archive"
    )

@app.route("/accounting_account_delete")
@xero_token_required
def accounting_account_delete():
    code = get_code_snippet("ACCOUNTS","DELETE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    # CREATE ACCOUNT
    account = Account(
        name="FooBar" + get_random_num(),
        code=get_random_num(),
        description="My Foobar",
        type=AccountType.EXPENSE,
    )

    try:
        created_accounts = accounting_api.create_account(
            xero_tenant_id, account
        )
        account_id = getvalue(created_accounts, "accounts.0.account_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[ACCOUNTS:DELETE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        deleted_accounts = accounting_api.delete_account(
            xero_tenant_id, account_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Account deleted."
        json = serialize_model(deleted_accounts)
    #[/ACCOUNTS:DELETE]

    return render_template(
        "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="delete"
    )

# BANK TRANSACTIONS
# getBankTransactions x
# createBankTransactions x
# updateOrCreateBankTransactions x
# getBankTransaction x
# updateBankTransaction x
# getBankTransactionAttachments x
# getBankTransactionAttachmentById x
# getBankTransactionAttachmentByFileName x
# updateBankTransactionAttachmentByFileName x
# createBankTransactionAttachmentByFileName x
# getBankTransactionsHistory x
# createBankTransactionHistoryRecord x

@app.route("/accounting_bank_transaction_read_all")
@xero_token_required
def accounting_bank_transaction_read_all():
    code = get_code_snippet("BANKTRANSACTIONS","READ_ALL")

    #[BANKTRANSACTIONS:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_bank_transactions = accounting_api.get_bank_transactions(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Bank Transactions read {} total".format(
            len(read_bank_transactions.bank_transactions)
        )
        json = serialize_model(read_bank_transactions)
    #[/BANKTRANSACTIONS:READ_ALL]

    return render_template(
        "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="read_all"
    )

@app.route("/accounting_bank_transaction_read_one")
@xero_token_required
def accounting_bank_transaction_read_one():
    code = get_code_snippet("BANKTRANSACTIONS","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_bank_transactions = accounting_api.get_bank_transactions(
            xero_tenant_id
        )
        bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[BANKTRANSACTIONS:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_one_bank_transaction = accounting_api.get_bank_transaction(
            xero_tenant_id, bank_transaction_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Bank transaction read with id {} ".format(
            getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
        )
        json = serialize_model(read_one_bank_transaction)
    #[/BANKTRANSACTIONS:READ_ONE]

    return render_template(
        "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="read_one"
    )

@app.route("/accounting_bank_transaction_create")
@xero_token_required
def accounting_bank_transaction_create():
    code = get_code_snippet("BANKTRANSACTIONS","CREATE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_contacts = accounting_api.get_contacts(
            xero_tenant_id
        )
        contact_id = getvalue(read_contacts, "contacts.0.contact_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    where = "TaxType!=\"NONE\" AND TaxType!=\"BASEXCLUDED\""
    try:
        read_accounts_for_valid_code = accounting_api.get_accounts(
            xero_tenant_id, where=where
        )
        account_code = getvalue(read_accounts_for_valid_code, "accounts.0.code", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    where = "Status==\"ACTIVE\" AND Type==\"BANK\""
    try:
        read_accounts_for_valid_status = accounting_api.get_accounts(
            xero_tenant_id, where=where
        )
        account_id = getvalue(read_accounts_for_valid_status, "accounts.0.account_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[BANKTRANSACTIONS:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    line_item = LineItem(
        description="consulting",
        quantity=1.0,
        unit_amount=20.0,
        account_code=account_code
    )

    contact = Contact(contact_id=contact_id)
    bank_account = Account(account_id=account_id)

    bank_transaction = BankTransaction(
        type="SPEND",
        contact=contact,
        line_items=[line_item],
        bank_account=bank_account,
        date=dateutil.parser.parse("2020-07-03T00:00:00Z")
    )

    bank_transactions = BankTransactions(bank_transactions=[bank_transaction])

    try:
        created_bank_transactions = accounting_api.create_bank_transactions(
            xero_tenant_id, bank_transactions=bank_transactions
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Bank transaction created with id {} .".format(
            getvalue(created_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
        )
        json = serialize_model(created_bank_transactions)
    #[/BANKTRANSACTIONS:CREATE]

    return render_template(
        "output.html", title="Bank Transactions", code=code, output=output, json=json, len = 0, set="accounting", endpoint="bank_transaction", action="create"
    )

@app.route("/accounting_bank_transaction_update_or_create")
@xero_token_required
def accounting_bank_transaction_update_or_create():
    code = get_code_snippet("BANKTRANSACTIONS","UPDATE_OR_CREATE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_contacts = accounting_api.get_contacts(
            xero_tenant_id
        )
        contact_id = getvalue(read_contacts, "contacts.0.contact_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    where = "TaxType!=\"NONE\" AND TaxType!=\"BASEXCLUDED\""
    try:
        read_accounts_for_valid_code = accounting_api.get_accounts(
            xero_tenant_id, where=where
        )
        account_code = getvalue(read_accounts_for_valid_code, "accounts.0.code", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    where = "Status==\"ACTIVE\" AND Type==\"BANK\""
    try:
        read_accounts_for_valid_status = accounting_api.get_accounts(
            xero_tenant_id, where=where
        )
        account_id = getvalue(read_accounts_for_valid_status, "accounts.0.account_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[BANKTRANSACTIONS:UPDATE_OR_CREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    contact = Contact(
        contact_id = contact_id)

    line_item = LineItem(
        description = "Foobar",
        quantity = 1.0,
        unit_amount = 20.0,
        account_code = account_code)

    bank_account = Account(
        account_id = account_id)

    bank_transaction = BankTransaction(
        type = "RECEIVE",
        contact = contact,
        line_items = [line_item],
        bank_account = bank_account)

    bank_transactions = BankTransactions(
        bank_transactions = [bank_transaction])

    try:
        update_create_bank_transactions = accounting_api.update_or_create_bank_transactions(
            xero_tenant_id, bank_transactions
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Bank transaction created or updated with id {} .".format(
            getvalue(update_create_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
        )
        json = serialize_model(update_create_bank_transactions)
    #[/BANKTRANSACTIONS:UPDATE_OR_CREATE]

    return render_template(
        "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="update_or_create"
    )

@app.route("/accounting_bank_transaction_update")
@xero_token_required
def accounting_bank_transaction_update():
    code = get_code_snippet("BANKTRANSACTIONS","UPDATE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    where = "Status!=\"VOIDED\""
    try:
        read_bank_transactions = accounting_api.get_bank_transactions(
            xero_tenant_id, where=where
        )
        bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    try:
        read_contacts = accounting_api.get_contacts(
            xero_tenant_id
        )
        contact_id = getvalue(read_contacts, "contacts.0.contact_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    where = "TaxType!=\"NONE\" AND TaxType!=\"BASEXCLUDED\""
    try:
        read_accounts_for_valid_code = accounting_api.get_accounts(
            xero_tenant_id, where=where
        )
        account_code = getvalue(read_accounts_for_valid_code, "accounts.0.code", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    where = "Status==\"ACTIVE\" AND Type==\"BANK\""
    try:
        read_accounts_for_valid_status = accounting_api.get_accounts(
            xero_tenant_id, where=where
        )
        account_id = getvalue(read_accounts_for_valid_status, "accounts.0.account_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[BANKTRANSACTIONS:UPDATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    bank_transaction_id = bank_transaction_id

    contact = Contact(
        contact_id = contact_id)

    line_item = LineItem(
        description = "Foobar",
        quantity = 1.0,
        unit_amount = 20.0,
        account_code = account_code)

    bank_account = Account(
        account_id = account_id)

    bank_transaction = BankTransaction(
        type = "RECEIVE",
        contact = contact,
        line_items = [line_item],
        bank_account = bank_account)

    bank_transactions = BankTransactions(
        bank_transactions = [bank_transaction])

    try:
        updated_bank_transactions = accounting_api.update_bank_transaction(
            xero_tenant_id, bank_transaction_id, bank_transactions
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Bank transaction updated with id {} .".format(
            getvalue(updated_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
        )
        json = serialize_model(updated_bank_transactions)
    #[/BANKTRANSACTIONS:UPDATE]

    return render_template(
        "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="update"
    )

@app.route("/accounting_bank_transaction_get_attachments")
@xero_token_required
def accounting_bank_transaction_get_attachments():
    code = get_code_snippet("BANKTRANSACTIONS","GET_ATTACHMENTS")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_bank_transactions = accounting_api.get_bank_transactions(
            xero_tenant_id
        )
        bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        try:
            include_online = True
            file_name = "helo-heros.jpg"
            path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
            open_file = open(path_to_upload, 'rb')
            body = open_file.read()
            content_type = mimetypes.MimeTypes().guess_type(file_name)[0]
            bank_transaction_attachment_created = accounting_api.create_bank_transaction_attachment_by_file_name(
                xero_tenant_id,
                bank_transaction_id,
                file_name,
                body,
            )
        except AccountingBadRequestException as exception:
            output = "Error: " + exception.reason
            json = jsonify(exception.error_data)

    # GET BANKTRANSACTION ATTACHMENTS
    #[BANKTRANSACTIONS:GET_ATTACHMENTS]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_bank_transaction_attachments = accounting_api.get_bank_transaction_attachments(
            xero_tenant_id, bank_transaction_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Bank Transaction attachments read {} total".format(
            len(read_bank_transaction_attachments.attachments)
        )
        json = serialize_model(read_bank_transaction_attachments)
    #[/BANKTRANSACTIONS:GET_ATTACHMENTS]

    return render_template(
        "output.html", title="Bank Transactions", code=code, output=output, json=json, len = 0, set="accounting", endpoint="bank_transaction", action="get_attachments"
    )

@app.route("/accounting_bank_transaction_get_attachment_by_id")
@xero_token_required
def accounting_bank_transaction_get_attachment_by_id():
    code = get_code_snippet("BANKTRANSACTIONS","GET_ATTACHMENTS_BY_ID")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_bank_transactions = accounting_api.get_bank_transactions(
            xero_tenant_id
        )
        bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        try:
            include_online = True
            file_name = "helo-heros.jpg"
            path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
            open_file = open(path_to_upload, 'rb')
            body = open_file.read()
            content_type = mimetypes.MimeTypes().guess_type(file_name)[0]
            bank_transaction_attachment_created = accounting_api.create_bank_transaction_attachment_by_file_name(
                xero_tenant_id,
                bank_transaction_id,
                file_name,
                body,
            )
            attachment_id = getvalue(bank_transaction_attachment_created, "attachments.0.attachment_id", "")
        except AccountingBadRequestException as exception:
            output = "Error: " + exception.reason
            json = jsonify(exception.error_data)

    # GET BANKTRANSACTION ATTACHMENTS
    #[BANKTRANSACTIONS:GET_ATTACHMENTS_BY_ID]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_bank_transaction_attachments = accounting_api.get_bank_transaction_attachment_by_id(
            xero_tenant_id, bank_transaction_id, attachment_id, content_type
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Bank Transaction attachment read with ID {} ".format(
            getvalue(read_bank_transaction_attachments, "attachments.0.attachment_id", "")
        )
        json = serialize_model(read_bank_transaction_attachments)
    #[/BANKTRANSACTIONS:GET_ATTACHMENTS_BY_ID]

    return render_template(
        "output.html", title="Bank Transactions", code=code, output=output, json=json, len = 0, set="accounting", endpoint="bank_transaction", action="get_attachment_by_id"
    )

@app.route("/accounting_bank_transaction_get_attachment_by_file_name")
@xero_token_required
def accounting_bank_transaction_get_attachment_by_file_name():
    code = get_code_snippet("BANKTRANSACTIONS","GET_ATTACHMENT_BY_FILE_NAME")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_bank_transactions = accounting_api.get_bank_transactions(
            xero_tenant_id
        )
        bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        try:
            include_online = True
            file_name = "helo-heros.jpg"
            path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
            open_file = open(path_to_upload, 'rb')
            body = open_file.read()
            content_type = mimetypes.MimeTypes().guess_type(file_name)[0]
            bank_transaction_attachment_created = accounting_api.create_bank_transaction_attachment_by_file_name(
                xero_tenant_id,
                bank_transaction_id,
                file_name,
                body,
            )
            file_name = getvalue(bank_transaction_attachment_created, "attachments.0.file_name", "")
        except AccountingBadRequestException as exception:
            output = "Error: " + exception.reason
            json = jsonify(exception.error_data)

    # GET BANKTRANSACTION ATTACHMENTS
    #[BANKTRANSACTIONS:GET_ATTACHMENT_BY_FILE_NAME]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_bank_transaction_attachments = accounting_api.get_bank_transaction_attachment_by_file_name(
            xero_tenant_id, bank_transaction_id, file_name, content_type
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Bank Transaction attachment read with file name {} ".format(
            getvalue(read_bank_transaction_attachments, "attachments.0.file_name", "")
        )
        json = serialize_model(read_bank_transaction_attachments)
    #[/BANKTRANSACTIONS:GET_ATTACHMENT_BY_FILE_NAME]

    return render_template(
        "output.html", title="Bank Transactions", code=code, output=output, json=json, len = 0, set="accounting", endpoint="bank_transaction", action="get_attachment_by_file_name"
    )

@app.route("/accounting_bank_transaction_attachment_create_by_file_name")
@xero_token_required
def accounting_bank_transaction_attachment_create_by_file_name():
    code = get_code_snippet("BANKTRANSACTIONATTACHMENTS","CREATEBYFILENAME")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_bank_transactions = accounting_api.get_bank_transactions(
            xero_tenant_id
        )
        bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[BANKTRANSACTIONATTACHMENTS:CREATEBYFILENAME]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    include_online = True
    file_name = "helo-heros.jpg"
    path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
    open_file = open(path_to_upload, 'rb')
    body = open_file.read()
    content_type = mimetypes.MimeTypes().guess_type(file_name)[0]

    try:
        created_bank_transaction_attachments_by_file_name = accounting_api.create_bank_transaction_attachment_by_file_name(
            xero_tenant_id,
            bank_transaction_id,
            file_name,
            body,
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Bank Transaction attachment created with url {} .".format(
            getvalue(created_bank_transaction_attachments_by_file_name, "attachments.0.url", "")
        )
        json = serialize_model(created_bank_transaction_attachments_by_file_name)
    
    #[/BANKTRANSACTIONATTACHMENTS:CREATEBYFILENAME]

    return render_template(
        "output.html", title="Bank Transactions", code=code, output=output, json=json, len = 0, set="accounting", endpoint="bank_transaction", action="create_attachment_by_file_name"
    )

@app.route("/accounting_bank_transaction_update_attachment")
@xero_token_required
def accounting_bank_transaction_update_attachment():
    code = get_code_snippet("BANKTRANSACTIONS","UPDATE_ATTACHMENT")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_bank_transactions = accounting_api.get_bank_transactions(
            xero_tenant_id
        )
        bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        try:
            include_online = True
            file_name = "helo-heros.jpg"
            path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
            open_file = open(path_to_upload, 'rb')
            body = open_file.read()
            content_type = mimetypes.MimeTypes().guess_type(file_name)[0]
            bank_transaction_attachment_created = accounting_api.create_bank_transaction_attachment_by_file_name(
                xero_tenant_id,
                bank_transaction_id,
                file_name,
                body,
            )
            file_name = getvalue(bank_transaction_attachment_created, "attachments.0.file_name", "")
        except AccountingBadRequestException as exception:
            output = "Error: " + exception.reason
            json = jsonify(exception.error_data)

    # UPDATE BANKTRANSACTION ATTACHMENT
    #[BANKTRANSACTIONS:UPDATE_ATTACHMENT]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        include_online = True
        file_name = file_name
        path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
        open_file = open(path_to_upload, 'rb')
        body = open_file.read()
        content_type = mimetypes.MimeTypes().guess_type(file_name)[0]
        bank_transaction_attachment_updated = accounting_api.update_bank_transaction_attachment_by_file_name(
            xero_tenant_id,
            bank_transaction_id,
            file_name,
            body,
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Attachment name '{}' updated.".format(
            getvalue(bank_transaction_attachment_updated, "attachments.0.file_name", "")
        )
        json = serialize_model(bank_transaction_attachment_updated)
    #[/BANKTRANSACTIONS:UPDATE_ATTACHMENT]

    return render_template(
        "output.html", title="Bank Transactions", code=code, output=output, json=json, len = 0, set="accounting", endpoint="bank_transaction", action="update_attachment"
    )

@app.route("/accounting_bank_transaction_history_read")
@xero_token_required
def accounting_bank_transaction_history_read():
    code = get_code_snippet("BANKTRANSACTIONHISTORY","READ")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_bank_transactions = accounting_api.get_bank_transactions(
            xero_tenant_id
        )
        bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[BANKTRANSACTIONHISTORY:READ]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_bank_transaction_history = accounting_api.get_bank_transactions_history(
            xero_tenant_id, bank_transaction_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Bank Transaction History read {} total".format(
            len(read_bank_transaction_history.history_records)
        )
        json = serialize_model(read_bank_transaction_history)
    #[/BANKTRANSACTIONHISTORY:READ]

    return render_template(
        "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="read_history"
    )

@app.route("/accounting_bank_transaction_history_create")
@xero_token_required
def accounting_bank_transaction_history_create():
    code = get_code_snippet("BANKTRANSACTIONHISTORY","CREATE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_bank_transactions = accounting_api.get_bank_transactions(
            xero_tenant_id
        )
        bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[BANKTRANSACTIONHISTORY:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    history_record = HistoryRecord(
        details = "I'm a history record " + get_random_num()
    )

    history_records = HistoryRecords(
        history_records = [history_record]
    )

    try:
        create_bank_transaction_history = accounting_api.create_bank_transaction_history_record(
            xero_tenant_id, bank_transaction_id, history_records
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Bank transaction history added with details {} .".format(
            getvalue(create_bank_transaction_history, "history_records.0.details", "")
        )
        json = serialize_model(create_bank_transaction_history)
    #[/BANKTRANSACTIONHISTORY:CREATE]

    return render_template(
        "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="create_history"
    )

# BANK TRANSFERS TODO
# getBankTransfers x
# createBankTransfer x
# getBankTransfer x
# getBankTransferAttachments x
# getBankTransferAttachmentById x
# getBankTransferAttachmentByFileName x
# updateBankTransferAttachmentByFileName x
# createBankTransferAttachmentByFileName x
# getBankTransferHistory
# createBankTransferHistoryRecord

@app.route("/accounting_bank_transfer_read_all")
@xero_token_required
def accounting_bank_transfer_read_all():
    code = get_code_snippet("BANKTRANSFERS","READ_ALL")

    #[BANKTRANSFERS:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_bank_transfers = accounting_api.get_bank_transfers(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Bank Transfers read {} total".format(
            len(read_bank_transfers.bank_transfers)
        )
        json = serialize_model(read_bank_transfers)
    #[/BANKTRANSFERS:READ_ALL]

    return render_template(
        "output.html", title="Bank Transfers", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transfer", action="read_all"
    )

@app.route("/accounting_bank_transfer_read_one")
@xero_token_required
def accounting_bank_transfer_read_one():
    code = get_code_snippet("BANKTRANSFERS","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_bank_transfers = accounting_api.get_bank_transfers(
            xero_tenant_id
        )
        bank_transfer_id = getvalue(read_bank_transfers, "bank_transfers.0.bank_transfer_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[BANKTRANSFERS:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_one_bank_transfer = accounting_api.get_bank_transfer(
            xero_tenant_id, bank_transfer_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Bank transfer read with id {} ".format(
            getvalue(read_bank_transfers, "bank_transfers.0.bank_transfer_id", "")
        )
        json = serialize_model(read_one_bank_transfer)
    #[/BANKTRANSFERS:READ_ONE]

    return render_template(
        "output.html", title="Bank Transfers", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transfer", action="read_one"
    )

@app.route("/accounting_bank_transfer_create")
@xero_token_required
def accounting_bank_transfer_create():
    code = get_code_snippet("BANKTRANSFERS","CREATE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    new_account_1 = Account(
        name="FooBar" + get_random_num(),
        code=get_random_num(),
        type=AccountType.BANK,
        bank_account_number=str(20908765432105)+str(randint(1,9))
    )

    new_account_2 = Account(
        name="FooBar" + get_random_num(),
        code=get_random_num(),
        type=AccountType.BANK,
        bank_account_number=str(20908765432105)+str(randint(1,9))
    )

    try:
        create_account_1 = accounting_api.create_account(
            xero_tenant_id, new_account_1
        )
        account_1_code = getvalue(create_account_1, "accounts.0.code", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    try:
        create_account_2 = accounting_api.create_account(
            xero_tenant_id, new_account_2
        )
        account_2_code = getvalue(create_account_2, "accounts.0.code", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[BANKTRANSFERS:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    account_1 = Account(code=account_1_code)

    account_2 = Account(code=account_2_code)

    bank_transfer = BankTransfer(
        from_bank_account=account_1,
        to_bank_account=account_2,
        amount=1000
    )

    bank_transfers = BankTransfers(bank_transfers=[bank_transfer])

    try:
        created_bank_transfers = accounting_api.create_bank_transfer(
            xero_tenant_id, bank_transfers
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Bank transfer created with id {} .".format(
            getvalue(created_bank_transfers, "bank_transfers.0.bank_transfer_id", "")
        )
        json = serialize_model(created_bank_transfers)
    #[/BANKTRANSFERS:CREATE]

    return render_template(
        "output.html", title="Bank Transfers", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transfer", action="create"
    )

@app.route("/accounting_bank_transfer_get_attachments")
@xero_token_required
def accounting_bank_transfer_get_attachments():
    code = get_code_snippet("BANKTRANSFERS","GET_ATTACHMENTS")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    new_account_1 = Account(
        name="FooBar" + get_random_num(),
        code=get_random_num(),
        type=AccountType.BANK,
        bank_account_number=str(20908765432105)+str(randint(1,9))
    )

    new_account_2 = Account(
        name="FooBar" + get_random_num(),
        code=get_random_num(),
        type=AccountType.BANK,
        bank_account_number=str(20908765432105)+str(randint(1,9))
    )

    try:
        create_account_1 = accounting_api.create_account(
            xero_tenant_id, new_account_1
        )
        account_1_code = getvalue(create_account_1, "accounts.0.code", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    try:
        create_account_2 = accounting_api.create_account(
            xero_tenant_id, new_account_2
        )
        account_2_code = getvalue(create_account_2, "accounts.0.code", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    account_1 = Account(code=account_1_code)

    account_2 = Account(code=account_2_code)

    bank_transfer = BankTransfer(
        from_bank_account=account_1,
        to_bank_account=account_2,
        amount=1000
    )

    bank_transfers = BankTransfers(bank_transfers=[bank_transfer])

    try:
        created_bank_transfers = accounting_api.create_bank_transfer(
            xero_tenant_id, bank_transfers
        )
        bank_transfer_id = getvalue(created_bank_transfers, "bank_transfers.0.bank_transfer_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        try:
            include_online = True
            file_name = "helo-heros.jpg"
            path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
            open_file = open(path_to_upload, 'rb')
            body = open_file.read()
            content_type = mimetypes.MimeTypes().guess_type(file_name)[0]
            bank_transfer_attachment_created = accounting_api.create_bank_transfer_attachment_by_file_name(
                xero_tenant_id,
                bank_transfer_id,
                file_name,
                body,
            )
        except AccountingBadRequestException as exception:
            output = "Error: " + exception.reason
            json = jsonify(exception.error_data)

    # GET BANKTRANSFER ATTACHMENTS
    #[BANKTRANSFERS:GET_ATTACHMENTS]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_bank_transfer_attachments = accounting_api.get_bank_transfer_attachments(
            xero_tenant_id, bank_transfer_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Bank Transfer attachments read {} total".format(
            len(read_bank_transfer_attachments.attachments)
        )
        json = serialize_model(read_bank_transfer_attachments)
    #[/BANKTRANSFERS:GET_ATTACHMENTS]

    return render_template(
        "output.html", title="Bank Transfers", code=code, output=output, json=json, len = 0, set="accounting", endpoint="bank_transfer", action="get_attachments"
    )

@app.route("/accounting_bank_transfer_get_attachment_by_id")
@xero_token_required
def accounting_bank_transfer_get_attachment_by_id():
    code = get_code_snippet("BANKTRANSFERS","GET_ATTACHMENTS_BY_ID")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    new_account_1 = Account(
        name="FooBar" + get_random_num(),
        code=get_random_num(),
        type=AccountType.BANK,
        bank_account_number=str(20908765432105)+str(randint(1,9))
    )

    new_account_2 = Account(
        name="FooBar" + get_random_num(),
        code=get_random_num(),
        type=AccountType.BANK,
        bank_account_number=str(20908765432105)+str(randint(1,9))
    )

    try:
        create_account_1 = accounting_api.create_account(
            xero_tenant_id, new_account_1
        )
        account_1_code = getvalue(create_account_1, "accounts.0.code", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    try:
        create_account_2 = accounting_api.create_account(
            xero_tenant_id, new_account_2
        )
        account_2_code = getvalue(create_account_2, "accounts.0.code", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    account_1 = Account(code=account_1_code)

    account_2 = Account(code=account_2_code)

    bank_transfer = BankTransfer(
        from_bank_account=account_1,
        to_bank_account=account_2,
        amount=1000
    )

    bank_transfers = BankTransfers(bank_transfers=[bank_transfer])

    try:
        created_bank_transfers = accounting_api.create_bank_transfer(
            xero_tenant_id, bank_transfers
        )
        bank_transfer_id = getvalue(created_bank_transfers, "bank_transfers.0.bank_transfer_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        try:
            include_online = True
            file_name = "helo-heros.jpg"
            path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
            open_file = open(path_to_upload, 'rb')
            body = open_file.read()
            content_type = mimetypes.MimeTypes().guess_type(file_name)[0]
            bank_transfer_attachment_created = accounting_api.create_bank_transfer_attachment_by_file_name(
                xero_tenant_id,
                bank_transfer_id,
                file_name,
                body,
            )
            attachment_id = getvalue(bank_transfer_attachment_created, "attachments.0.attachment_id", "")
        except AccountingBadRequestException as exception:
            output = "Error: " + exception.reason
            json = jsonify(exception.error_data)

    # GET BANKTRANSFER ATTACHMENTS
    #[BANKTRANSFERS:GET_ATTACHMENTS_BY_ID]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_bank_transfer_attachments = accounting_api.get_bank_transfer_attachment_by_id(
            xero_tenant_id, bank_transfer_id, attachment_id, content_type
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Bank Transfer attachment read with ID {} ".format(
            getvalue(read_bank_transfer_attachments, "attachments.0.attachment_id", "")
        )
        json = serialize_model(read_bank_transfer_attachments)
    #[/BANKTRANSFERS:GET_ATTACHMENTS_BY_ID]

    return render_template(
        "output.html", title="Bank Transfers", code=code, output=output, json=json, len = 0, set="accounting", endpoint="bank_transfer", action="get_attachment_by_id"
    )

@app.route("/accounting_bank_transfer_get_attachment_by_file_name")
@xero_token_required
def accounting_bank_transfer_get_attachment_by_file_name():
    code = get_code_snippet("BANKTRANSFERS","GET_ATTACHMENT_BY_FILE_NAME")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    new_account_1 = Account(
        name="FooBar" + get_random_num(),
        code=get_random_num(),
        type=AccountType.BANK,
        bank_account_number=str(20908765432105)+str(randint(1,9))
    )

    new_account_2 = Account(
        name="FooBar" + get_random_num(),
        code=get_random_num(),
        type=AccountType.BANK,
        bank_account_number=str(20908765432105)+str(randint(1,9))
    )

    try:
        create_account_1 = accounting_api.create_account(
            xero_tenant_id, new_account_1
        )
        account_1_code = getvalue(create_account_1, "accounts.0.code", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    try:
        create_account_2 = accounting_api.create_account(
            xero_tenant_id, new_account_2
        )
        account_2_code = getvalue(create_account_2, "accounts.0.code", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    account_1 = Account(code=account_1_code)

    account_2 = Account(code=account_2_code)

    bank_transfer = BankTransfer(
        from_bank_account=account_1,
        to_bank_account=account_2,
        amount=1000
    )

    bank_transfers = BankTransfers(bank_transfers=[bank_transfer])

    try:
        created_bank_transfers = accounting_api.create_bank_transfer(
            xero_tenant_id, bank_transfers
        )
        bank_transfer_id = getvalue(created_bank_transfers, "bank_transfers.0.bank_transfer_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        try:
            include_online = True
            file_name = "helo-heros.jpg"
            path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
            open_file = open(path_to_upload, 'rb')
            body = open_file.read()
            content_type = mimetypes.MimeTypes().guess_type(file_name)[0]
            bank_transfer_attachment_created = accounting_api.create_bank_transfer_attachment_by_file_name(
                xero_tenant_id,
                bank_transfer_id,
                file_name,
                body,
            )
            file_name = getvalue(bank_transfer_attachment_created, "attachments.0.file_name", "")
        except AccountingBadRequestException as exception:
            output = "Error: " + exception.reason
            json = jsonify(exception.error_data)

    # GET BANKTRANSFER ATTACHMENTS
    #[BANKTRANSFERS:GET_ATTACHMENT_BY_FILE_NAME]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_bank_transfer_attachments = accounting_api.get_bank_transfer_attachment_by_file_name(
            xero_tenant_id, bank_transfer_id, file_name, content_type
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Bank Transfer attachment read with file name {} ".format(
            getvalue(read_bank_transfer_attachments, "attachments.0.file_name", "")
        )
        json = serialize_model(read_bank_transfer_attachments)
    #[/BANKTRANSFERS:GET_ATTACHMENT_BY_FILE_NAME]

    return render_template(
        "output.html", title="Bank Transfers", code=code, output=output, json=json, len = 0, set="accounting", endpoint="bank_transfer", action="get_attachment_by_file_name"
    )

@app.route("/accounting_bank_transfer_attachment_create_by_file_name")
@xero_token_required
def accounting_bank_transfer_attachment_create_by_file_name():
    code = get_code_snippet("BANKTRANSFERATTACHMENTS","CREATEBYFILENAME")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    new_account_1 = Account(
        name="FooBar" + get_random_num(),
        code=get_random_num(),
        type=AccountType.BANK,
        bank_account_number=str(20908765432105)+str(randint(1,9))
    )

    new_account_2 = Account(
        name="FooBar" + get_random_num(),
        code=get_random_num(),
        type=AccountType.BANK,
        bank_account_number=str(20908765432105)+str(randint(1,9))
    )

    try:
        create_account_1 = accounting_api.create_account(
            xero_tenant_id, new_account_1
        )
        account_1_code = getvalue(create_account_1, "accounts.0.code", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    try:
        create_account_2 = accounting_api.create_account(
            xero_tenant_id, new_account_2
        )
        account_2_code = getvalue(create_account_2, "accounts.0.code", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    account_1 = Account(code=account_1_code)

    account_2 = Account(code=account_2_code)

    bank_transfer = BankTransfer(
        from_bank_account=account_1,
        to_bank_account=account_2,
        amount=1000
    )

    bank_transfers = BankTransfers(bank_transfers=[bank_transfer])

    try:
        created_bank_transfers = accounting_api.create_bank_transfer(
            xero_tenant_id, bank_transfers
        )
        bank_transfer_id = getvalue(created_bank_transfers, "bank_transfers.0.bank_transfer_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[BANKTRANSFERATTACHMENTS:CREATEBYFILENAME]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    include_online = True
    file_name = "helo-heros.jpg"
    path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
    open_file = open(path_to_upload, 'rb')
    body = open_file.read()
    content_type = mimetypes.MimeTypes().guess_type(file_name)[0]

    try:
        created_bank_transfer_attachments_by_file_name = accounting_api.create_bank_transfer_attachment_by_file_name(
            xero_tenant_id,
            bank_transfer_id,
            file_name,
            body,
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Bank Transfer attachment created with url {} .".format(
            getvalue(created_bank_transfer_attachments_by_file_name, "attachments.0.url", "")
        )
        json = serialize_model(created_bank_transfer_attachments_by_file_name)
    
    #[/BANKTRANSFERATTACHMENTS:CREATEBYFILENAME]

    return render_template(
        "output.html", title="Bank Transfers", code=code, output=output, json=json, len = 0, set="accounting", endpoint="bank_transfer", action="create_attachment_by_file_name"
    )

@app.route("/accounting_bank_transfer_update_attachment")
@xero_token_required
def accounting_bank_transfer_update_attachment():
    code = get_code_snippet("BANKTRANSFERS","UPDATE_ATTACHMENT")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    new_account_1 = Account(
        name="FooBar" + get_random_num(),
        code=get_random_num(),
        type=AccountType.BANK,
        bank_account_number=str(20908765432105)+str(randint(1,9))
    )

    new_account_2 = Account(
        name="FooBar" + get_random_num(),
        code=get_random_num(),
        type=AccountType.BANK,
        bank_account_number=str(20908765432105)+str(randint(1,9))
    )

    try:
        create_account_1 = accounting_api.create_account(
            xero_tenant_id, new_account_1
        )
        account_1_code = getvalue(create_account_1, "accounts.0.code", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    try:
        create_account_2 = accounting_api.create_account(
            xero_tenant_id, new_account_2
        )
        account_2_code = getvalue(create_account_2, "accounts.0.code", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    account_1 = Account(code=account_1_code)

    account_2 = Account(code=account_2_code)

    bank_transfer = BankTransfer(
        from_bank_account=account_1,
        to_bank_account=account_2,
        amount=1000
    )

    bank_transfers = BankTransfers(bank_transfers=[bank_transfer])

    try:
        created_bank_transfers = accounting_api.create_bank_transfer(
            xero_tenant_id, bank_transfers
        )
        bank_transfer_id = getvalue(created_bank_transfers, "bank_transfers.0.bank_transfer_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        try:
            include_online = True
            file_name = "helo-heros.jpg"
            path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
            open_file = open(path_to_upload, 'rb')
            body = open_file.read()
            content_type = mimetypes.MimeTypes().guess_type(file_name)[0]
            bank_transfer_attachment_created = accounting_api.create_bank_transfer_attachment_by_file_name(
                xero_tenant_id,
                bank_transfer_id,
                file_name,
                body,
            )
        except AccountingBadRequestException as exception:
            output = "Error: " + exception.reason
            json = jsonify(exception.error_data)

    # UPDATE BANKTRANSFER ATTACHMENT
    #[BANKTRANSFERS:UPDATE_ATTACHMENT]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        include_online = True
        file_name = file_name
        path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
        open_file = open(path_to_upload, 'rb')
        body = open_file.read()
        content_type = mimetypes.MimeTypes().guess_type(file_name)[0]
        bank_transfer_attachment_updated = accounting_api.update_bank_transfer_attachment_by_file_name(
            xero_tenant_id,
            bank_transfer_id,
            file_name,
            body,
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Attachment name '{}' updated.".format(
            getvalue(bank_transfer_attachment_updated, "attachments.0.file_name", "")
        )
        json = serialize_model(bank_transfer_attachment_updated)
    #[/BANKTRANSFERS:UPDATE_ATTACHMENT]

    return render_template(
        "output.html", title="Bank Transfers", code=code, output=output, json=json, len = 0, set="accounting", endpoint="bank_transfer", action="update_attachment"
    )

# @app.route("/accounting_bank_transaction_history_read")
# @xero_token_required
# def accounting_bank_transaction_history_read():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","READ")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:READ]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transaction_history = accounting_api.get_bank_transactions_history(
#             xero_tenant_id, bank_transaction_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank Transaction History read {} total".format(
#             len(read_bank_transaction_history.history_records)
#         )
#         json = serialize_model(read_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:READ]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="read_history"
#     )

# @app.route("/accounting_bank_transaction_history_create")
# @xero_token_required
# def accounting_bank_transaction_history_create():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","CREATE")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:CREATE]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     history_record = HistoryRecord(
#         details = "I'm a history record " + get_random_num()
#     )

#     history_records = HistoryRecords(
#         history_records = [history_record]
#     )

#     try:
#         create_bank_transaction_history = accounting_api.create_bank_transaction_history_record(
#             xero_tenant_id, bank_transaction_id, history_records
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank transaction history added with details {} .".format(
#             getvalue(create_bank_transaction_history, "history_records.0.details", "")
#         )
#         json = serialize_model(create_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:CREATE]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="create_history"
#     )

# BATCH PAYMENTS TODO
# getBatchPayments x
# createBatchPayment x
# getBatchPaymentHistory
# createBatchPaymentHistoryRecord

@app.route("/accounting_batch_payment_read_all")
@xero_token_required
def accounting_batch_payment_read_all():
    code = get_code_snippet("BATCHPAYMENTS","READ_ALL")

    #[BATCHPAYMENTS:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_batch_payments = accounting_api.get_batch_payments(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Batch Payments read {} total".format(
            len(read_batch_payments.batch_payments)
        )
        json = serialize_model(read_batch_payments)
    #[/BATCHPAYMENTS:READ_ALL]

    return render_template(
        "output.html", title="Batch Payments", code=code, json=json, output=output, len = 0, set="accounting", endpoint="batch_payment", action="read_all"
    )

@app.route("/accounting_batch_payment_read_one")
@xero_token_required
def accounting_batch_payment_read_one():
    code = get_code_snippet("BATCHPAYMENTS","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_batch_payments = accounting_api.get_batch_payments(
            xero_tenant_id
        )
        batch_payment_id = getvalue(read_batch_payments, "batch_payments.0.batch_payment_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[BATCHPAYMENTS:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_one_batch_payment = accounting_api.get_batch_payment(
            xero_tenant_id, batch_payment_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Batch Payment read with id {} ".format(
            getvalue(read_one_batch_payment, "batch_payments.0.batch_payment_id", "")
        )
        json = serialize_model(read_one_batch_payment)
    #[/BATCHPAYMENTS:READ_ONE]

    return render_template(
        "output.html", title="Batch Payments", code=code, json=json, output=output, len = 0, set="accounting", endpoint="batch_payment", action="read_one"
    )

@app.route("/accounting_batch_payment_create")
@xero_token_required
def accounting_batch_payment_create():
    code = get_code_snippet("BATCHPAYMENTS","CREATE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    # we need a contact
    try:
        contacts = accounting_api.get_contacts(
            xero_tenant_id
        )
        contact_id = getvalue(contacts, "contacts.0.contact_id", "")
        contact = Contact(contact_id)
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    # we need an account of type BANK
    where = "Type==\"BANK\""
    try:
        accounts = accounting_api.get_accounts(
            xero_tenant_id, where
        )
        account_id = getvalue(accounts, "accounts.0.account_id", "")
        account = Account(account_id=account_id)
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    # we need multiple invoices
    line_item = LineItem(
        description="Consulting services",
        quantity=20,
        unit_amount=100.00,
        account_code="200"
    )

    invoice_1 = Invoice(
        type="ACCREC",
        contact=contact,
        date=dateutil.parser.parse("2020-12-03T00:00:00"),
        due_date=dateutil.parser.parse("2021-01-06T00:00:00"),
        line_items=[line_item],
        status="AUTHORISED"
    )
    invoice_2 = Invoice(
        type="ACCREC",
        contact=contact,
        date=dateutil.parser.parse("2020-12-03T00:00:00"),
        due_date=dateutil.parser.parse("2021-01-18T00:00:00"),
        line_items=[line_item],
        status="AUTHORISED"
    )
    invoices = Invoices(invoices=[invoice_1, invoice_2])

    try:
        created_invoices = accounting_api.create_invoices(
            xero_tenant_id, invoices
        )
        invoice_1_id = getvalue(created_invoices, "invoices.0.invoice_id", "")
        invoice_2_id = getvalue(created_invoices, "invoices.1.invoice_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[BATCHPAYMENTS:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    invoice_1 = Invoice(invoice_id=invoice_1_id)
    invoice_2 = Invoice(invoice_id=invoice_2_id)

    payment_1 = Payment(
        reference="something 1",
        invoice=invoice_1,
        amount=3.50
    )
    payment_2 = Payment(
        reference="something 2",
        invoice=invoice_2,
        amount=7.25
    )

    batch_payment = BatchPayment(
        date=dateutil.parser.parse("2020-12-24"),
        reference="Something",
        account=account,
        payments=[payment_1, payment_2]
    )

    batch_payments = BatchPayments(batch_payments=[batch_payment])

    try:
        created_batch_payments = accounting_api.create_batch_payment(
            xero_tenant_id, batch_payments
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Batch payment created with id {} .".format(
            getvalue(created_batch_payments, "batch_payments.0.batch_payment_id", "")
        )
        json = serialize_model(created_batch_payments)
    #[/BATCHPAYMENTS:CREATE]

    return render_template(
        "output.html", title="Batch Payments", code=code, json=json, output=output, len = 0, set="accounting", endpoint="batch_payment", action="create"
    )

# @app.route("/accounting_bank_transaction_history_read")
# @xero_token_required
# def accounting_bank_transaction_history_read():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","READ")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:READ]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transaction_history = accounting_api.get_bank_transactions_history(
#             xero_tenant_id, bank_transaction_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank Transaction History read {} total".format(
#             len(read_bank_transaction_history.history_records)
#         )
#         json = serialize_model(read_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:READ]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="read_history"
#     )

# @app.route("/accounting_bank_transaction_history_create")
# @xero_token_required
# def accounting_bank_transaction_history_create():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","CREATE")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:CREATE]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     history_record = HistoryRecord(
#         details = "I'm a history record " + get_random_num()
#     )

#     history_records = HistoryRecords(
#         history_records = [history_record]
#     )

#     try:
#         create_bank_transaction_history = accounting_api.create_bank_transaction_history_record(
#             xero_tenant_id, bank_transaction_id, history_records
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank transaction history added with details {} .".format(
#             getvalue(create_bank_transaction_history, "history_records.0.details", "")
#         )
#         json = serialize_model(create_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:CREATE]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="create_history"
#     )

# BRANDING THEMES
# getBrandingThemes x
# getBrandingTheme x
# getBrandingThemePaymentServices x
# createBrandingThemePaymentServices x

@app.route("/accounting_branding_theme_read_all")
@xero_token_required
def accounting_branding_theme_read_all():
    code = get_code_snippet("BRANDINGTHEMES","READ_ALL")

    #[BRANDINGTHEMES:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_branding_themes = accounting_api.get_branding_themes(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Branding Themes read {} total".format(
            len(read_branding_themes.branding_themes)
        )
        json = serialize_model(read_branding_themes)
    #[/BRANDINGTHEMES:READ_ALL]

    return render_template(
        "output.html", title="Branding Themes", code=code, json=json, output=output, len = 0, set="accounting", endpoint="branding_theme", action="read_all"
    )

@app.route("/accounting_branding_theme_read_one")
@xero_token_required
def accounting_branding_theme_read_one():
    code = get_code_snippet("BRANDINGTHEMES","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_branding_themes = accounting_api.get_branding_themes(
            xero_tenant_id
        )
        branding_theme_id = getvalue(read_branding_themes, "branding_themes.0.branding_theme_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[BRANDINGTHEMES:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_one_branding_theme = accounting_api.get_branding_theme(
            xero_tenant_id, branding_theme_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Branding theme read with id {} ".format(
            getvalue(read_branding_themes, "branding_themes.0.branding_theme_id", "")
        )
        json = serialize_model(read_one_branding_theme)
    #[/BRANDINGTHEMES:READ_ONE]

    return render_template(
        "output.html", title="Branding Themes", code=code, json=json, output=output, len = 0, set="accounting", endpoint="branding_theme", action="read_one"
    )

@app.route("/accounting_branding_theme_payment_service_read_all")
@xero_token_required
def accounting_branding_theme_payment_service_read_all():
    code = get_code_snippet("BRANDINGTHEMEPAYMENTSERVICES","READ_ALL")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)
    
    try:
        read_branding_themes = accounting_api.get_branding_themes(
            xero_tenant_id
        )
        branding_theme_id = getvalue(read_branding_themes, "branding_themes.0.branding_theme_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[BRANDINGTHEMEPAYMENTSERVICES:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_branding_theme_payment_services = accounting_api.get_branding_theme_payment_services(
            xero_tenant_id, branding_theme_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Branding Theme Payment Services read {} total".format(
            len(read_branding_theme_payment_services.payment_services)
        )
        json = serialize_model(read_branding_theme_payment_services)
    #[/BRANDINGTHEMEPAYMENTSERVICES:READ_ALL]

    return render_template(
        "output.html", title="Branding Themes", code=code, json=json, output=output, len = 0, set="accounting", endpoint="branding_theme_payment_service", action="read_all"
    )

@app.route("/accounting_branding_theme_payment_service_create")
@xero_token_required
def accounting_branding_theme_payment_service_create():
    code = get_code_snippet("BRANDINGTHEMEPAYMENTSERVICES","CREATE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    # we'll need a payment service
    new_payment_service = PaymentService(
        payment_service_name="PayUpNow " + get_random_num(),
        payment_service_url="https://www.payupnow.com/?invoiceNo=[INVOICENUMBER]&currency=[CURRENCY]&amount=[AMOUNTDUE]&shortCode=[SHORTCODE]",
        pay_now_text="Time To Pay"
    )

    payment_services = PaymentServices(payment_services=[new_payment_service])

    try:
        created_payment_services = accounting_api.create_payment_service(
            xero_tenant_id, payment_services
        )
        payment_service_id = getvalue(created_payment_services, "payment_services.0.payment_service_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    # we'll also need a branding theme
    try:
        read_branding_themes = accounting_api.get_branding_themes(
            xero_tenant_id
        )
        branding_theme_id = getvalue(read_branding_themes, "branding_themes.0.branding_theme_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[BRANDINGTHEMEPAYMENTSERVICES:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    payment_service = PaymentService(payment_service_id=payment_service_id)

    try:
        created_branding_theme_payment_service = accounting_api.create_branding_theme_payment_services(
            xero_tenant_id, branding_theme_id, payment_service
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Branding theme payment service created with id {} .".format(
            getvalue(created_branding_theme_payment_service, "payment_services.0.payment_service_id", "")
        )
        json = serialize_model(created_branding_theme_payment_service)
    #[/BRANDINGTHEMEPAYMENTSERVICES:CREATE]

    return render_template(
        "output.html", title="Branding Themes", code=code, json=json, output=output, len = 0, set="accounting", endpoint="branding_theme_payment_service", action="create"
    )

# BUDGETS TODO
# *** coming April 2021 ***

# CONTACTS TODO
# getContacts x
# createContacts x
# updateOrCreateContacts x
# getContactByContactNumber x
# getContact x
# updateContact x
# getContactAttachments
# getContactAttachmentById
# getContactAttachmentByFileName
# updateContactAttachmentByFileName
# createContactAttachmentByFileName
# getContactCISSettings
# getContactHistory
# createContactHistory

@app.route("/accounting_contact_create_multiple")
@xero_token_required
def accounting_contact_create_multiple():
    code = get_code_snippet("CONTACTS","CREATE_MULTIPLE")

    #[CONTACTS:CREATE_MULTIPLE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    contact = Contact(
        name="George-" + get_random_num(),
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
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        result_list = None
        json = jsonify(exception.error_data)
    else:
        output = ""
        result_list = []
        for contact in created_contacts.contacts:
            if contact.has_validation_errors:
                error = getvalue(contact.validation_errors, "0.message", "")
                result_list.append("Error: {}".format(error))
            else:
                result_list.append("Contact {} created.".format(contact.name))

        json = serialize_model(created_contacts)
    #[/CONTACTS:CREATE_MULTIPLE]

    return render_template(
        "output.html", title="Contacts", result_list=result_list, code=code, json=json, len=0, set="accounting", endpoint="contact", action="create_multiple"
    )

@app.route("/accounting_contact_create")
@xero_token_required
def accounting_contact_create():
    code = get_code_snippet("CONTACTS","CREATE")

    #[CONTACTS:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    contact_person = ContactPerson(
        first_name="John",
        last_name="Smith",
        email_address="john.smith@24locks.com",
        include_in_emails=True,
    )

    contact = Contact(
        name="FooBar" + get_random_num(),
        first_name="Foo",
        last_name="Bar",
        email_address="ben.bowden@24locks.com",
        contact_persons=[contact_person],
    )

    contacts = Contacts(contacts=[contact])

    try:
        created_contact = accounting_api.create_contacts(
            xero_tenant_id, contacts=contacts
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Contact {} created.".format(
            getvalue(created_contact, "contacts.0.name", "")
        )
        json = serialize_model(created_contact)
    #[/CONTACTS:CREATE]

    return render_template(
        "output.html",  title="Contacts", code=code, output=output, json=json, len = 0,  set="accounting", endpoint="contact", action="create"
    )

@app.route("/accounting_contact_update_or_create")
@xero_token_required
def accounting_contact_update_or_create():
    code = get_code_snippet("CONTACTS","UPDATE_OR_CREATE")

    #[CONTACTS:UPDATE_OR_CREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    phone = Phone(
        phone_number = "555-1212",
        phone_type = "MOBILE")
    phones = []
    phones.append(phone)

    contact = Contact(
        name = "Bruce Banner " + get_random_num(),
        email_address = "hulk@avengers.com",
        phones = phones)

    contacts = Contacts(
        contacts = [contact])

    try:
        updated_or_created_contact = accounting_api.update_or_create_contacts(
            xero_tenant_id, contacts=contacts
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Contact {} updated or created.".format(
            getvalue(updated_or_created_contact, "contacts.0.name", "")
        )
        json = serialize_model(updated_or_created_contact)
    #[/CONTACTS:UPDATE_OR_CREATE]

    return render_template(
        "output.html",  title="Contacts", code=code, output=output, json=json, len = 0,  set="accounting", endpoint="contact", action="update_or_create"
    )

@app.route("/accounting_contact_update")
@xero_token_required
def accounting_contact_update():
    code = get_code_snippet("CONTACTS","UPDATE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_contacts = accounting_api.get_contacts(
            xero_tenant_id
        )
        contact_id = getvalue(read_contacts, "contacts.0.contact_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[CONTACTS:UPDATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    contact_id = contact_id

    contact = Contact(
        name = "Thanos",
        contact_id = contact_id)

    contacts = Contacts(
        contacts = [contact])

    try:
        updated_or_created_contact = accounting_api.update_contact(
            xero_tenant_id, contact_id, contacts=contacts
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Contact {} updated.".format(
            getvalue(updated_or_created_contact, "contacts.0.name", "")
        )
        json = serialize_model(updated_or_created_contact)
    #[/CONTACTS:UPDATE]

    return render_template(
        "output.html",  title="Contacts", code=code, output=output, json=json, len = 0,  set="accounting", endpoint="contact", action="update"
    )

@app.route("/accounting_contact_read_all")
@xero_token_required
def accounting_contact_read_all():
    code = get_code_snippet("CONTACTS","READ_ALL")

    #[CONTACTS:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_contacts = accounting_api.get_contacts(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Contact(s) read {} total".format(
            len(read_contacts.contacts)
        )
        json = serialize_model(read_contacts)
    #[/CONTACTS:READ_ALL]

    return render_template(
        "output.html", title="Contacts", code=code, json=json, output=output, len = 0, set="accounting", endpoint="contact", action="read_all"
    )

@app.route("/accounting_contact_read_one")
@xero_token_required
def accounting_contact_read_one():
    code = get_code_snippet("CONTACTS","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_contacts = accounting_api.get_contacts(
            xero_tenant_id
        )
        contact_id = getvalue(read_contacts, "contacts.0.contact_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[CONTACTS:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_one_contact = accounting_api.get_contact(
            xero_tenant_id, contact_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Contact read with id {} ".format(
            getvalue(read_one_contact, "contacts.0.contact_id", "")
        )
        json = serialize_model(read_one_contact)
    #[/CONTACTS:READ_ONE]

    return render_template(
        "output.html", title="Contacts", code=code, json=json, output=output, len = 0, set="accounting", endpoint="contact", action="read_one"
    )

@app.route("/accounting_contact_read_one_by_contact_number")
@xero_token_required
def accounting_contact_read_one_by_contact_number():
    code = get_code_snippet("CONTACTS","READ_ONE_BY_CONTACT_NUMBER")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_contacts = accounting_api.get_contacts(
            xero_tenant_id
        )
        contact_number = getvalue(read_contacts, "contacts.0.contact_number", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[CONTACTS:READ_ONE_BY_CONTACT_NUMBER]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    contact_number=contact_number

    try:
        read_one_contact = accounting_api.get_contact_by_contact_number(
            xero_tenant_id, contact_number
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Contact read with number {} ".format(
            getvalue(read_one_contact, "contacts.0.contact_number", "")
        )
        json = serialize_model(read_one_contact)
    #[/CONTACTS:READ_ONE_BY_CONTACT_NUMBER]

    return render_template(
        "output.html", title="Contacts", code=code, json=json, output=output, len = 0, set="accounting", endpoint="contact", action="read_one_by_number"
    )

# @app.route("/accounting_account_get_attachments")
# @xero_token_required
# def accounting_account_get_attachments():
#     code = get_code_snippet("ACCOUNTS","GET_ATTACHMENTS")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     # CREATE ACCOUNT
#     account = Account(
#         name="FooBar" + get_random_num(),
#         code=get_random_num(),
#         description="My Foobar",
#         type=AccountType.EXPENSE,
#     )

#     try:
#         created_accounts = accounting_api.create_account(
#             xero_tenant_id, account
#         )
#         account_id = getvalue(created_accounts, "accounts.0.account_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         try:
#             include_online = True
#             myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
#             with myimage.open("rb") as image:
#                 account_attachment_created = accounting_api.create_account_attachment_by_file_name(
#                     xero_tenant_id,
#                     account_id,
#                     file_name=myimage.name,
#                     body=image.read(),
#                 )
#         except AccountingBadRequestException as exception:
#             output = "Error: " + exception.reason
#             json = jsonify(exception.error_data)

#     # GET ACCOUNT ATTACHMENTS
#     #[ACCOUNTS:GET_ATTACHMENTS]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_account_attachments = accounting_api.get_account_attachments(
#             xero_tenant_id, account_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Account attachments read {} total".format(
#             len(read_account_attachments.attachments)
#         )
#         json = serialize_model(read_account_attachments)
#     #[/ACCOUNTS:GET_ATTACHMENTS]

#     return render_template(
#         "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="get_attachments"
#     )

# @app.route("/accounting_account_get_attachment_by_id")
# @xero_token_required
# def accounting_account_get_attachment_by_id():
#     code = get_code_snippet("ACCOUNTS","GET_ATTACHMENTS")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     # CREATE ACCOUNT
#     account = Account(
#         name="FooBar" + get_random_num(),
#         code=get_random_num(),
#         description="My Foobar",
#         type=AccountType.EXPENSE,
#     )

#     try:
#         created_accounts = accounting_api.create_account(
#             xero_tenant_id, account
#         )
#         account_id = getvalue(created_accounts, "accounts.0.account_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         try:
#             include_online = True
#             myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
#             with myimage.open("rb") as image:
#                 account_attachment_created = accounting_api.create_account_attachment_by_file_name(
#                     xero_tenant_id,
#                     account_id,
#                     file_name=myimage.name,
#                     body=image.read(),
#                 )
#         except AccountingBadRequestException as exception:
#             output = "Error: " + exception.reason
#             json = jsonify(exception.error_data)

#     # GET ACCOUNT ATTACHMENTS
#     #[ACCOUNTS:GET_ATTACHMENTS]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_account_attachments = accounting_api.get_account_attachments(
#             xero_tenant_id, account_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Account attachments read {} total".format(
#             len(read_account_attachments.attachments)
#         )
#         json = serialize_model(read_account_attachments)
#     #[/ACCOUNTS:GET_ATTACHMENTS]

#     return render_template(
#         "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="get_attachments"
#     )

# @app.route("/accounting_account_get_attachment_by_file_name")
# @xero_token_required
# def accounting_account_get_attachment_by_file_name():
#     code = get_code_snippet("ACCOUNTS","GET_ATTACHMENTS")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     # CREATE ACCOUNT
#     account = Account(
#         name="FooBar" + get_random_num(),
#         code=get_random_num(),
#         description="My Foobar",
#         type=AccountType.EXPENSE,
#     )

#     try:
#         created_accounts = accounting_api.create_account(
#             xero_tenant_id, account
#         )
#         account_id = getvalue(created_accounts, "accounts.0.account_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         try:
#             include_online = True
#             myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
#             with myimage.open("rb") as image:
#                 account_attachment_created = accounting_api.create_account_attachment_by_file_name(
#                     xero_tenant_id,
#                     account_id,
#                     file_name=myimage.name,
#                     body=image.read(),
#                 )
#         except AccountingBadRequestException as exception:
#             output = "Error: " + exception.reason
#             json = jsonify(exception.error_data)

#     # GET ACCOUNT ATTACHMENTS
#     #[ACCOUNTS:GET_ATTACHMENTS]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_account_attachments = accounting_api.get_account_attachments(
#             xero_tenant_id, account_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Account attachments read {} total".format(
#             len(read_account_attachments.attachments)
#         )
#         json = serialize_model(read_account_attachments)
#     #[/ACCOUNTS:GET_ATTACHMENTS]

#     return render_template(
#         "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="get_attachments"
#     )

# @app.route("/accounting_bank_transaction_attachment_create_by_file_name")
# @xero_token_required
# def accounting_bank_transaction_attachment_create_by_file_name():
#     code = get_code_snippet("BANKTRANSACTIONATTACHMENTS","CREATEBYFILENAME")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONATTACHMENTS:CREATEBYFILENAME]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     file_name = "helo-heros.jpg"
#     path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
#     open_file = open(path_to_upload, 'rb')
#     body = open_file.read()

#     try:
#         created_bank_transaction_attachments_by_file_name = accounting_api.create_bank_transaction_attachment_by_file_name(
#             xero_tenant_id, bank_transaction_id, file_name, body
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank transaction attachment created with url {} .".format(
#             getvalue(created_bank_transaction_attachments_by_file_name, "attachments.0.url", "")
#         )
#         json = serialize_model(created_bank_transaction_attachments_by_file_name)
    
#     #[/BANKTRANSACTIONATTACHMENTS:CREATEBYFILENAME]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, output=output, json=json, len = 0, set="accounting", endpoint="bank_transaction", action="create_attachment_by_file_name"
#     )

# @app.route("/accounting_account_update_attachment")
# @xero_token_required
# def accounting_account_update_attachment():
#     code = get_code_snippet("ACCOUNTS","CREATE_ATTACHMENT")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     # CREATE ACCOUNT
#     account = Account(
#         name="FooBar" + get_random_num(),
#         code=get_random_num(),
#         description="My Foobar",
#         type=AccountType.EXPENSE,
#     )

#     try:
#         created_accounts = accounting_api.create_account(
#             xero_tenant_id, account
#         )
#         account_id = getvalue(created_accounts, "accounts.0.account_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     # CREATE ACCOUNT ATTACHMENT
#     #[ACCOUNTS:CREATE_ATTACHMENT]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         include_online = True
#         myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
#         with myimage.open("rb") as image:
#             account_attachment_created = accounting_api.create_account_attachment_by_file_name(
#                 xero_tenant_id,
#                 account_id,
#                 file_name=myimage.name,
#                 body=image.read(),
#             )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Attachment url '{}' created.".format(
#             getvalue(account_attachment_created, "attachments.0.url", "")
#         )
#         json = serialize_model(account_attachment_created)
#     #[/ACCOUNTS:CREATE_ATTACHMENT]

#     return render_template(
#         "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="create_attachment"
#     )

# @app.route("/accounting_bank_transaction_history_read")
# @xero_token_required
# def accounting_bank_transaction_history_read():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","READ")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:READ]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transaction_history = accounting_api.get_bank_transactions_history(
#             xero_tenant_id, bank_transaction_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank Transaction History read {} total".format(
#             len(read_bank_transaction_history.history_records)
#         )
#         json = serialize_model(read_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:READ]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="read_history"
#     )

# @app.route("/accounting_bank_transaction_history_create")
# @xero_token_required
# def accounting_bank_transaction_history_create():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","CREATE")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:CREATE]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     history_record = HistoryRecord(
#         details = "I'm a history record " + get_random_num()
#     )

#     history_records = HistoryRecords(
#         history_records = [history_record]
#     )

#     try:
#         create_bank_transaction_history = accounting_api.create_bank_transaction_history_record(
#             xero_tenant_id, bank_transaction_id, history_records
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank transaction history added with details {} .".format(
#             getvalue(create_bank_transaction_history, "history_records.0.details", "")
#         )
#         json = serialize_model(create_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:CREATE]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="create_history"
#     )

# CONTACT GROUPS TODO
# getContactGroups x
# createContactGroup x
# getContactGroup x
# updateContactGroup x
# createContactGroupContacts x
# deleteContactGroupContacts
# deleteContactGroupContact

@app.route("/accounting_contact_group_read_all")
@xero_token_required
def accounting_contact_group_read_all():
    code = get_code_snippet("CONTACTGROUPS","READ_ALL")

    #[CONTACTGROUPS:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_contact_groups = accounting_api.get_contact_groups(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Contact Groups read {} total".format(
            len(read_contact_groups.contact_groups)
        )
        json = serialize_model(read_contact_groups)
    #[/CONTACTGROUPS:READ_ALL]

    return render_template(
        "output.html", title="Contact Groups", code=code, json=json, output=output, len = 0, set="accounting", endpoint="contact_group", action="read_all"
    )

@app.route("/accounting_contact_group_read_one")
@xero_token_required
def accounting_contact_group_read_one():
    code = get_code_snippet("CONTACTGROUPS","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_contact_groups = accounting_api.get_contact_groups(
            xero_tenant_id
        )
        contact_group_id = getvalue(read_contact_groups, "contact_groups.0.contact_group_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[CONTACTGROUPS:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_one_contact_group = accounting_api.get_contact_group(
            xero_tenant_id, contact_group_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Contact group read with id {} ".format(
            getvalue(read_contact_groups, "contact_groups.0.contact_group_id", "")
        )
        json = serialize_model(read_one_contact_group)
    #[/CONTACTGROUPS:READ_ONE]

    return render_template(
        "output.html", title="Contact Groups", code=code, json=json, output=output, len = 0, set="accounting", endpoint="contact_group", action="read_one"
    )

@app.route("/accounting_contact_group_create")
@xero_token_required
def accounting_contact_group_create():
    code = get_code_snippet("CONTACTGROUPS","CREATE")

    #[CONTACTGROUPS:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    contact_group = ContactGroup(
        name="Ima Contact Group " + get_random_num()
    )

    contact_groups = ContactGroups(contact_groups=[contact_group])

    try:
        created_contact_group = accounting_api.create_contact_group(
            xero_tenant_id, contact_groups=contact_groups
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Contact group {} created.".format(
            getvalue(created_contact_group, "contact_groups.0.name", "")
        )
        json = serialize_model(created_contact_group)
    #[/CONTACTGROUPS:CREATE]

    return render_template(
        "output.html",  title="Contact Groups", code=code, output=output, json=json, len = 0,  set="accounting", endpoint="contact_group", action="create"
    )

@app.route("/accounting_contact_group_contacts_create")
@xero_token_required
def accounting_contact_group_contacts_create():
    code = get_code_snippet("CONTACTGROUPCONTACTS","CREATE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_contact_groups = accounting_api.get_contact_groups(
            xero_tenant_id
        )
        contact_group_id = getvalue(read_contact_groups, "contact_groups.0.contact_group_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    try:
        read_contacts = accounting_api.get_contacts(
            xero_tenant_id
        )
        contact_id = getvalue(read_contacts, "contacts.0.contact_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[CONTACTGROUPCONTACTS:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    contact_group_id = contact_group_id

    contact = Contact(
        contact_id = contact_id)

    contacts = Contacts(
        contacts = [contact])

    try:
        created_contact_group_contact = accounting_api.create_contact_group_contacts(
            xero_tenant_id, contact_group_id, contacts
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Contact group contact {} created.".format(
            getvalue(created_contact_group_contact, "contacts.0.contact_id", "")
        )
        json = serialize_model(created_contact_group_contact)
    #[/CONTACTGROUPCONTACTS:CREATE]

    return render_template(
        "output.html",  title="Contact Groups", code=code, output=output, json=json, len = 0,  set="accounting", endpoint="contact_group", action="create_contact"
    )

@app.route("/accounting_contact_group_update")
@xero_token_required
def accounting_contact_group_update():
    code = get_code_snippet("CONTACTGROUPS","UPDATE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_contact_groups = accounting_api.get_contact_groups(
            xero_tenant_id
        )
        contact_group_id = getvalue(read_contact_groups, "contact_groups.0.contact_group_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[CONTACTGROUPS:UPDATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    contact_group_id = contact_group_id

    contact_group = ContactGroup(
        name = "Vendor " + get_random_num())

    contact_groups = ContactGroups(
        contact_groups = [contact_group])

    try:
        updated_contact_groups = accounting_api.update_contact_group(
            xero_tenant_id, contact_group_id, contact_groups=contact_groups
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Contact group {} updated.".format(
            getvalue(updated_contact_groups, "contact_groups.0.name", "")
        )
        json = serialize_model(updated_contact_groups)
    #[/CONTACTGROUPS:UPDATE]

    return render_template(
        "output.html", title="Contact Groups", code=code, json=json, output=output, len = 0, set="accounting", endpoint="contact_group", action="update"
    )

# CREDIT NOTES TODO
# getCreditNotes x
# createCreditNotes x
# updateOrCreateCreditNotes x
# getCreditNote x
# updateCreditNote x
# createCreditNoteAllocation x
# getCreditNoteAttachments
# getCreditNoteAttachmentById
# getCreditNoteAttachmentByFileName
# updateCreditNoteAttachmentByFileName
# createCreditNoteAttachmentByFileName
# getCreditNoteAsPdf
# getCreditNoteHistory
# createCreditNoteHistory

@app.route("/accounting_credit_note_read_all")
@xero_token_required
def accounting_credit_note_read_all():
    code = get_code_snippet("CREDITNOTES","READ_ALL")

    #[CREDITNOTES:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_credit_notes = accounting_api.get_credit_notes(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Credit Notes read {} total".format(
            len(read_credit_notes.credit_notes)
        )
        json = serialize_model(read_credit_notes)
    #[/CREDITNOTES:READ_ALL]

    return render_template(
        "output.html", title="Credit Notes", code=code, json=json, output=output, len = 0, set="accounting", endpoint="credit_note", action="read_all"
    )

@app.route("/accounting_credit_note_read_one")
@xero_token_required
def accounting_credit_note_read_one():
    code = get_code_snippet("CREDITNOTES","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_credit_notes = accounting_api.get_credit_notes(
            xero_tenant_id
        )
        credit_note_id = getvalue(read_credit_notes, "credit_notes.0.credit_note_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[CREDITNOTES:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_one_credit_note = accounting_api.get_credit_note(
            xero_tenant_id, credit_note_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Credit note read with id {} ".format(
            getvalue(read_credit_notes, "credit_notes.0.credit_note_id", "")
        )
        json = serialize_model(read_one_credit_note)
    #[/CREDITNOTES:READ_ONE]

    return render_template(
        "output.html", title="Credit Notes", code=code, json=json, output=output, len = 0, set="accounting", endpoint="credit_note", action="read_one"
    )

@app.route("/accounting_credit_note_create")
@xero_token_required
def accounting_credit_note_create():
    code = get_code_snippet("CREDITNOTES","CREATE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    # we're going to need a contact
    try:
        read_contacts = accounting_api.get_contacts(
            xero_tenant_id
        )
        contact_id = getvalue(read_contacts, "contacts.0.contact_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    # we're going to need an account
    where = "Type==\"SALES\"&&Status==\"ACTIVE\""
    try:
        read_accounts = accounting_api.get_accounts(
            xero_tenant_id, where=where
        )
        account_id = getvalue(read_accounts, "accounts.0.account_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    # we're going to need an invoice for that contact
    contact = Contact(
        contact_id=contact_id
    )

    line_item = LineItem(
        account_code=account_id,
        description="Consulting",
        quantity=1.0,
        unit_amount=10.0,
    )

    invoice = Invoice(
        line_items=[line_item],
        contact=contact,
        due_date=dateutil.parser.parse("2020-09-03T00:00:00Z"),
        date=dateutil.parser.parse("2020-07-03T00:00:00Z"),
        type="ACCREC"
    )

    invoices = Invoices(invoices=[invoice])

    try:
        created_invoices = accounting_api.create_invoices(
            xero_tenant_id, invoices=invoices
        )
        invoice_id = getvalue(created_invoices, "invoices.0.invoice_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[CREDITNOTES:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    credit_note = CreditNote(
        type="ACCRECCREDIT",
        status="DRAFT",
        contact=contact,
        date= dateutil.parser.parse("2020-07-03T00:00:00Z"),
        line_amount_types=LineAmountTypes.EXCLUSIVE,
        line_items=[line_item]
    )

    credit_notes = CreditNotes(credit_notes=[credit_note])

    try:
        created_credit_note = accounting_api.create_credit_notes(
            xero_tenant_id, credit_notes=credit_notes
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Credit note created with id {} .".format(
            getvalue(created_credit_note, "credit_notes.0.credit_note_id", "")
        )
        json = serialize_model(created_credit_note)
    #[/CREDITNOTES:CREATE]

    return render_template(
        "output.html",  title="Credit Notes", code=code, output=output, json=json, len = 0,  set="accounting", endpoint="credit_note", action="create"
    )

@app.route("/accounting_credit_note_update_or_create")
@xero_token_required
def accounting_credit_note_update_or_create():
    code = get_code_snippet("CREDITNOTES","UPDATECREATE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_contacts = accounting_api.get_contacts(
            xero_tenant_id
        )
        contact_id = getvalue(read_contacts, "contacts.0.contact_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    where = "Type==\"SALES\"&&Status==\"ACTIVE\""
    try:
        read_accounts = accounting_api.get_accounts(
            xero_tenant_id, where=where
        )
        account_code = getvalue(read_accounts, "accounts.0.account_code", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[CREDITNOTES:UPDATECREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    curr_date = dateutil.parser.parse('2021-01-19T00:00:00Z')

    contact = Contact(
        contact_id = contact_id)

    line_item = LineItem(
        description = "Foobar",
        quantity = 1.0,
        unit_amount = 20.0,
        account_code = account_code)
    line_items = []
    line_items.append(line_item)

    credit_note = CreditNote(
        type = "ACCPAYCREDIT",
        contact = contact,
        date = curr_date,
        line_items = line_items)

    credit_notes = CreditNotes(
        credit_notes = [credit_note])

    try:
        update_or_created_credit_note = accounting_api.update_or_create_credit_notes(
            xero_tenant_id, credit_notes=credit_notes
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Credit note created or updated with id {} .".format(
            getvalue(update_or_created_credit_note, "credit_notes.0.credit_note_id", "")
        )
        json = serialize_model(update_or_created_credit_note)
    #[/CREDITNOTES:UPDATECREATE]

    return render_template(
        "output.html",  title="Credit Notes", code=code, output=output, json=json, len = 0,  set="accounting", endpoint="credit_note", action="update_or_create"
    )

@app.route("/accounting_credit_note_update")
@xero_token_required
def accounting_credit_note_update():
    code = get_code_snippet("CREDITNOTES","UPDATE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_contacts = accounting_api.get_contacts(
            xero_tenant_id
        )
        contact_id = getvalue(read_contacts, "contacts.0.contact_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    where = "Type==\"SALES\"&&Status==\"ACTIVE\""
    try:
        read_accounts = accounting_api.get_accounts(
            xero_tenant_id, where=where
        )
        account_code = getvalue(read_accounts, "accounts.0.account_code", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    where = "Status==\"SUBMITTED\""
    try:
        read_credit_notes = accounting_api.get_credit_notes(
            xero_tenant_id
        )
        credit_note_id = getvalue(read_credit_notes, "credit_notes.0.credit_note_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[CREDITNOTES:UPDATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)
    credit_note_id = credit_note_id
    curr_date = dateutil.parser.parse('2021-01-19T00:00:00Z')

    contact = Contact(
        contact_id = contact_id)

    line_item = LineItem(
        description = "Foobar",
        quantity = 1.0,
        unit_amount = 20.0,
        account_code = account_code)
    line_items = []
    line_items.append(line_item)

    credit_note = CreditNote(
        type = "ACCPAYCREDIT",
        status = "AUTHORISED",
        reference = "My ref.",
        contact = contact,
        date = curr_date,
        line_items = line_items)

    credit_notes = CreditNotes(
        credit_notes = [credit_note])

    try:
        updated_credit_note = accounting_api.update_credit_note(
            xero_tenant_id, credit_note_id, credit_notes=credit_notes
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Credit note updated with id {} .".format(
            getvalue(updated_credit_note, "credit_notes.0.credit_note_id", "")
        )
        json = serialize_model(updated_credit_note)
    #[/CREDITNOTES:UPDATE]

    return render_template(
        "output.html",  title="Credit Notes", code=code, output=output, json=json, len = 0,  set="accounting", endpoint="credit_note", action="update"
    )

@app.route("/accounting_credit_note_allocation_create")
@xero_token_required
def accounting_credit_note_allocation_create():
    code = get_code_snippet("CREDITNOTES","CREATE_ALLOCATION")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_credit_notes = accounting_api.get_credit_notes(
            xero_tenant_id
        )
        credit_note_id = getvalue(read_credit_notes, "credit_notes.0.credit_note_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    try:
        read_invoices = accounting_api.get_invoices(
            xero_tenant_id
        )
        invoice_id = getvalue(read_invoices, "invoices.0.invoice_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[CREDITNOTES:CREATE_ALLOCATION]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)
    curr_date = dateutil.parser.parse('2021-02-23T00:00:00Z')

    invoice = Invoice(
        invoice_id = invoice_id)
    
    allocation = Allocation(
        amount = 1.0,
        date = curr_date,
        invoice = invoice)
    
    allocations = Allocations(    
        allocations = [allocation])

    try:
        created_credit_note_allocation = accounting_api.create_credit_note_allocation(
            xero_tenant_id, credit_note_id, allocations
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Credit note allocation created with id {} .".format(
            getvalue(created_credit_note_allocation, "allocations.0.allocation_id", "")
        )
        json = serialize_model(created_credit_note_allocation)
    #[/CREDITNOTES:CREATE_ALLOCATION]

    return render_template(
        "output.html", title="Credit Notes", code=code, json=json, output=output, len = 0, set="accounting", endpoint="credit_note_allocation", action="create"
    )

# @app.route("/accounting_account_get_attachments")
# @xero_token_required
# def accounting_account_get_attachments():
#     code = get_code_snippet("ACCOUNTS","GET_ATTACHMENTS")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     # CREATE ACCOUNT
#     account = Account(
#         name="FooBar" + get_random_num(),
#         code=get_random_num(),
#         description="My Foobar",
#         type=AccountType.EXPENSE,
#     )

#     try:
#         created_accounts = accounting_api.create_account(
#             xero_tenant_id, account
#         )
#         account_id = getvalue(created_accounts, "accounts.0.account_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         try:
#             include_online = True
#             myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
#             with myimage.open("rb") as image:
#                 account_attachment_created = accounting_api.create_account_attachment_by_file_name(
#                     xero_tenant_id,
#                     account_id,
#                     file_name=myimage.name,
#                     body=image.read(),
#                 )
#         except AccountingBadRequestException as exception:
#             output = "Error: " + exception.reason
#             json = jsonify(exception.error_data)

#     # GET ACCOUNT ATTACHMENTS
#     #[ACCOUNTS:GET_ATTACHMENTS]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_account_attachments = accounting_api.get_account_attachments(
#             xero_tenant_id, account_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Account attachments read {} total".format(
#             len(read_account_attachments.attachments)
#         )
#         json = serialize_model(read_account_attachments)
#     #[/ACCOUNTS:GET_ATTACHMENTS]

#     return render_template(
#         "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="get_attachments"
#     )

# @app.route("/accounting_account_get_attachment_by_id")
# @xero_token_required
# def accounting_account_get_attachment_by_id():
#     code = get_code_snippet("ACCOUNTS","GET_ATTACHMENTS")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     # CREATE ACCOUNT
#     account = Account(
#         name="FooBar" + get_random_num(),
#         code=get_random_num(),
#         description="My Foobar",
#         type=AccountType.EXPENSE,
#     )

#     try:
#         created_accounts = accounting_api.create_account(
#             xero_tenant_id, account
#         )
#         account_id = getvalue(created_accounts, "accounts.0.account_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         try:
#             include_online = True
#             myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
#             with myimage.open("rb") as image:
#                 account_attachment_created = accounting_api.create_account_attachment_by_file_name(
#                     xero_tenant_id,
#                     account_id,
#                     file_name=myimage.name,
#                     body=image.read(),
#                 )
#         except AccountingBadRequestException as exception:
#             output = "Error: " + exception.reason
#             json = jsonify(exception.error_data)

#     # GET ACCOUNT ATTACHMENTS
#     #[ACCOUNTS:GET_ATTACHMENTS]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_account_attachments = accounting_api.get_account_attachments(
#             xero_tenant_id, account_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Account attachments read {} total".format(
#             len(read_account_attachments.attachments)
#         )
#         json = serialize_model(read_account_attachments)
#     #[/ACCOUNTS:GET_ATTACHMENTS]

#     return render_template(
#         "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="get_attachments"
#     )

# @app.route("/accounting_account_get_attachment_by_file_name")
# @xero_token_required
# def accounting_account_get_attachment_by_file_name():
#     code = get_code_snippet("ACCOUNTS","GET_ATTACHMENTS")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     # CREATE ACCOUNT
#     account = Account(
#         name="FooBar" + get_random_num(),
#         code=get_random_num(),
#         description="My Foobar",
#         type=AccountType.EXPENSE,
#     )

#     try:
#         created_accounts = accounting_api.create_account(
#             xero_tenant_id, account
#         )
#         account_id = getvalue(created_accounts, "accounts.0.account_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         try:
#             include_online = True
#             myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
#             with myimage.open("rb") as image:
#                 account_attachment_created = accounting_api.create_account_attachment_by_file_name(
#                     xero_tenant_id,
#                     account_id,
#                     file_name=myimage.name,
#                     body=image.read(),
#                 )
#         except AccountingBadRequestException as exception:
#             output = "Error: " + exception.reason
#             json = jsonify(exception.error_data)

#     # GET ACCOUNT ATTACHMENTS
#     #[ACCOUNTS:GET_ATTACHMENTS]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_account_attachments = accounting_api.get_account_attachments(
#             xero_tenant_id, account_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Account attachments read {} total".format(
#             len(read_account_attachments.attachments)
#         )
#         json = serialize_model(read_account_attachments)
#     #[/ACCOUNTS:GET_ATTACHMENTS]

#     return render_template(
#         "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="get_attachments"
#     )

# @app.route("/accounting_bank_transaction_attachment_create_by_file_name")
# @xero_token_required
# def accounting_bank_transaction_attachment_create_by_file_name():
#     code = get_code_snippet("BANKTRANSACTIONATTACHMENTS","CREATEBYFILENAME")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONATTACHMENTS:CREATEBYFILENAME]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     file_name = "helo-heros.jpg"
#     path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
#     open_file = open(path_to_upload, 'rb')
#     body = open_file.read()

#     try:
#         created_bank_transaction_attachments_by_file_name = accounting_api.create_bank_transaction_attachment_by_file_name(
#             xero_tenant_id, bank_transaction_id, file_name, body
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank transaction attachment created with url {} .".format(
#             getvalue(created_bank_transaction_attachments_by_file_name, "attachments.0.url", "")
#         )
#         json = serialize_model(created_bank_transaction_attachments_by_file_name)
    
#     #[/BANKTRANSACTIONATTACHMENTS:CREATEBYFILENAME]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, output=output, json=json, len = 0, set="accounting", endpoint="bank_transaction", action="create_attachment_by_file_name"
#     )

# @app.route("/accounting_account_update_attachment")
# @xero_token_required
# def accounting_account_update_attachment():
#     code = get_code_snippet("ACCOUNTS","CREATE_ATTACHMENT")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     # CREATE ACCOUNT
#     account = Account(
#         name="FooBar" + get_random_num(),
#         code=get_random_num(),
#         description="My Foobar",
#         type=AccountType.EXPENSE,
#     )

#     try:
#         created_accounts = accounting_api.create_account(
#             xero_tenant_id, account
#         )
#         account_id = getvalue(created_accounts, "accounts.0.account_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     # CREATE ACCOUNT ATTACHMENT
#     #[ACCOUNTS:CREATE_ATTACHMENT]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         include_online = True
#         myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
#         with myimage.open("rb") as image:
#             account_attachment_created = accounting_api.create_account_attachment_by_file_name(
#                 xero_tenant_id,
#                 account_id,
#                 file_name=myimage.name,
#                 body=image.read(),
#             )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Attachment url '{}' created.".format(
#             getvalue(account_attachment_created, "attachments.0.url", "")
#         )
#         json = serialize_model(account_attachment_created)
#     #[/ACCOUNTS:CREATE_ATTACHMENT]

#     return render_template(
#         "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="create_attachment"
#     )

# @app.route("/accounting_bank_transaction_history_read")
# @xero_token_required
# def accounting_bank_transaction_history_read():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","READ")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:READ]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transaction_history = accounting_api.get_bank_transactions_history(
#             xero_tenant_id, bank_transaction_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank Transaction History read {} total".format(
#             len(read_bank_transaction_history.history_records)
#         )
#         json = serialize_model(read_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:READ]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="read_history"
#     )

# @app.route("/accounting_bank_transaction_history_create")
# @xero_token_required
# def accounting_bank_transaction_history_create():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","CREATE")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:CREATE]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     history_record = HistoryRecord(
#         details = "I'm a history record " + get_random_num()
#     )

#     history_records = HistoryRecords(
#         history_records = [history_record]
#     )

#     try:
#         create_bank_transaction_history = accounting_api.create_bank_transaction_history_record(
#             xero_tenant_id, bank_transaction_id, history_records
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank transaction history added with details {} .".format(
#             getvalue(create_bank_transaction_history, "history_records.0.details", "")
#         )
#         json = serialize_model(create_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:CREATE]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="create_history"
#     )

# CURRENCIES
# getCurrencies x
# createCurrency x

@app.route("/accounting_currency_read_all")
@xero_token_required
def accounting_currency_read_all():
    code = get_code_snippet("CURRENCIES","READ_ALL")

    #[CURRENCIES:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_currencies = accounting_api.get_currencies(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Currencies read {} total".format(
            len(read_currencies.currencies)
        )
        json = serialize_model(read_currencies)
    #[/CURRENCIES:READ_ALL]

    return render_template(
        "output.html", title="Currencies", code=code, json=json, output=output, len = 0, set="accounting", endpoint="currency", action="read_all"
    )

@app.route("/accounting_currency_create")
@xero_token_required
def accounting_currency_create():
    code = get_code_snippet("CURRENCIES","CREATE")

    #[CURRENCIES:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    # CREATE only works once per currency code

    currency = Currency(
        code=CurrencyCode.ZAR
    )

    try:
        created_currency = accounting_api.create_currency(
            xero_tenant_id, currency
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Currency created with description {} .".format(
            getvalue(created_currency, "currencies.0.description", "")
        )
        json = serialize_model(created_currency)
    #[/CURRENCIES:CREATE]

    return render_template(
        "output.html", title="Currencies", code=code, json=json, output=output, len = 0, set="accounting", endpoint="currency", action="create"
    )

# EMPLOYEES
# getEmployees x
# createEmployees x
# updateOrCreateEmployees x
# getEmployee x

@app.route("/accounting_employee_read_all")
@xero_token_required
def accounting_employee_read_all():
    code = get_code_snippet("EMPLOYEES","READ_ALL")

    #[EMPLOYEES:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_employees = accounting_api.get_employees(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Employees read {} total".format(
            len(read_employees.employees)
        )
        json = serialize_model(read_employees)
    #[/EMPLOYEES:READ_ALL]

    return render_template(
        "output.html", title="Employees", code=code, json=json, output=output, len = 0, set="accounting", endpoint="employee", action="read_all"
    )

@app.route("/accounting_employee_read_one")
@xero_token_required
def accounting_employee_read_one():
    code = get_code_snippet("EMPLOYEES","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_employees = accounting_api.get_employees(
            xero_tenant_id
        )
        employee_id = getvalue(read_employees, "employees.0.employee_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[EMPLOYEES:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_one_employee = accounting_api.get_employee(
            xero_tenant_id, employee_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Employee read with id {} ".format(
            getvalue(read_employees, "employees.0.employee_id", "")
        )
        json = serialize_model(read_one_employee)
    #[/EMPLOYEES:READ_ONE]

    return render_template(
        "output.html", title="Employees", code=code, json=json, output=output, len = 0, set="accounting", endpoint="employee", action="read_one"
    )

@app.route("/accounting_employee_create")
@xero_token_required
def accounting_employee_create():
    code = get_code_snippet("EMPLOYEES","CREATE")

    #[EMPLOYEES:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    employee = Employee(
        first_name="First " + get_random_num(),
        last_name="Last " + get_random_num()
    )

    employees = Employees(employees=[employee])

    try:
        created_employee = accounting_api.create_employees(
            xero_tenant_id, employees
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Employee created with id {} .".format(
            getvalue(created_employee, "employees.0.employee_id", "")
        )
        json = serialize_model(created_employee)
    #[/EMPLOYEES:CREATE]

    return render_template(
        "output.html", title="Employees", code=code, json=json, output=output, len = 0, set="accounting", endpoint="employee", action="create"
    )

@app.route("/accounting_employee_update_or_create")
@xero_token_required
def accounting_employee_update_or_create():
    code = get_code_snippet("EMPLOYEES","UPDATEORCREATE")

    #[EMPLOYEES:UPDATEORCREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    employee = Employee(
        first_name="First " + get_random_num(),
        last_name="Last " + get_random_num()
    )

    employees = Employees(employees=[employee])

    try:
        updated_or_created_employee = accounting_api.update_or_create_employees(
            xero_tenant_id, employees
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Employee updated or created with id {} .".format(
            getvalue(updated_or_created_employee, "employees.0.employee_id", "")
        )
        json = serialize_model(updated_or_created_employee)
    #[/EMPLOYEES:UPDATEORCREATE]

    return render_template(
        "output.html", title="Employees", code=code, json=json, output=output, len = 0, set="accounting", endpoint="employee", action="update_or_create"
    )

# EXPENSE CLAIMS (DEPRECATED) TODO
# getExpenseClaims x
# getExpenseClaim x
# createExpenseClaims x
# updateExpenseClaim x
# getExpenseClaimHistory
# createExpenseClaimHistory

@app.route("/accounting_expense_claim_read_all")
@xero_token_required
def accounting_expense_claim_read_all():
    code = get_code_snippet("EXPENSECLAIMS","READ_ALL")

    #[EXPENSECLAIMS:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_expense_claims = accounting_api.get_expense_claims(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Expense Claims read {} total".format(
            len(read_expense_claims.expense_claims)
        )
        json = serialize_model(read_expense_claims)
    #[/EXPENSECLAIMS:READ_ALL]

    return render_template(
        "output.html", title="Expense Claims", code=code, json=json, output=output, len = 0, set="accounting", endpoint="expense_claim", action="read_all"
    )

@app.route("/accounting_expense_claim_read_one")
@xero_token_required
def accounting_expense_claim_read_one():
    code = get_code_snippet("EXPENSECLAIMS","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_expense_claims = accounting_api.get_expense_claims(
            xero_tenant_id
        )
        expense_claim_id = getvalue(read_expense_claims, "expense_claims.0.expense_claim_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[EXPENSECLAIMS:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_one_expense_claim = accounting_api.get_expense_claim(
            xero_tenant_id, expense_claim_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Expense claim read with id {} ".format(
            getvalue(read_expense_claims, "expense_claims.0.expense_claim_id", "")
        )
        json = serialize_model(read_one_expense_claim)
    #[/EXPENSECLAIMS:READ_ONE]

    return render_template(
        "output.html", title="Expense Claims", code=code, json=json, output=output, len = 0, set="accounting", endpoint="expense_claim", action="read_one"
    )

@app.route("/accounting_expense_claim_create")
@xero_token_required
def accounting_expense_claim_create():
    code = get_code_snippet("EXPENSECLAIMS","CREATE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_users = accounting_api.get_users(
            xero_tenant_id
        )
        user_id = getvalue(read_users, "users.0.user_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    
    try:
        read_receipts = accounting_api.get_receipts(
            xero_tenant_id
        )
        receipt_id = getvalue(read_receipts, "receipts.0.receipt_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[EXPENSECLAIMS:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)
    curr_date = dateutil.parser.parse('2020-12-03T00:00:00Z')

    user = User(
        user_id = user_id)
    
    receipt = Receipt(
        receipt_id = receipt_id,
        date = curr_date)
    
    receipts = []
    receipts.append(receipt)
    
    expense_claim = ExpenseClaim(
        status = "SUBMITTED",
        user = user,
        receipts = receipts)
    
    expense_claims = ExpenseClaims(    
        expense_claims = [expense_claim])

    try:
        created_expense_claims = accounting_api.create_expense_claims(
            xero_tenant_id, expense_claims
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Expense claim created with id {} ".format(
            getvalue(created_expense_claims, "expense_claims.0.expense_claim_id", "")
        )
        json = serialize_model(created_expense_claims)
    #[/EXPENSECLAIMS:CREATE]

    return render_template(
        "output.html", title="Expense Claims", code=code, json=json, output=output, len = 0, set="accounting", endpoint="expense_claim", action="create"
    )

@app.route("/accounting_expense_claim_update")
@xero_token_required
def accounting_expense_claim_update():
    code = get_code_snippet("EXPENSECLAIMS","UPDATE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_users = accounting_api.get_users(
            xero_tenant_id
        )
        user_id = getvalue(read_users, "users.0.user_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    
    try:
        read_receipts = accounting_api.get_receipts(
            xero_tenant_id
        )
        receipt_id = getvalue(read_receipts, "receipts.0.receipt_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    
    try:
        read_expense_claims = accounting_api.get_expense_claims(
            xero_tenant_id
        )
        expense_claim_id = getvalue(read_expense_claims, "expense_claims.0.expense_claim_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[EXPENSECLAIMS:UPDATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)
    curr_date = dateutil.parser.parse('2020-12-03T00:00:00Z')

    user = User(
        user_id = user_id)
    
    receipt = Receipt(
        receipt_id = receipt_id,
        date = curr_date)
    
    receipts = []
    receipts.append(receipt)
    
    expense_claim = ExpenseClaim(
        status = "PAID",
        user = user,
        receipts = receipts)
    
    expense_claims = ExpenseClaims(    
        expense_claims = [expense_claim])

    print(xero_tenant_id, expense_claim_id, expense_claims)

    try:
        updated_expense_claims = accounting_api.update_expense_claim(
            xero_tenant_id, expense_claim_id, expense_claims
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Expense claim updated with id {} ".format(
            getvalue(updated_expense_claims, "expense_claims.0.expense_claim_id", "")
        )
        json = serialize_model(updated_expense_claims)
    #[/EXPENSECLAIMS:UPDATE]

    return render_template(
        "output.html", title="Expense Claims", code=code, json=json, output=output, len = 0, set="accounting", endpoint="expense_claim", action="update"
    )

# @app.route("/accounting_bank_transaction_history_read")
# @xero_token_required
# def accounting_bank_transaction_history_read():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","READ")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:READ]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transaction_history = accounting_api.get_bank_transactions_history(
#             xero_tenant_id, bank_transaction_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank Transaction History read {} total".format(
#             len(read_bank_transaction_history.history_records)
#         )
#         json = serialize_model(read_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:READ]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="read_history"
#     )

# @app.route("/accounting_bank_transaction_history_create")
# @xero_token_required
# def accounting_bank_transaction_history_create():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","CREATE")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:CREATE]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     history_record = HistoryRecord(
#         details = "I'm a history record " + get_random_num()
#     )

#     history_records = HistoryRecords(
#         history_records = [history_record]
#     )

#     try:
#         create_bank_transaction_history = accounting_api.create_bank_transaction_history_record(
#             xero_tenant_id, bank_transaction_id, history_records
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank transaction history added with details {} .".format(
#             getvalue(create_bank_transaction_history, "history_records.0.details", "")
#         )
#         json = serialize_model(create_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:CREATE]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="create_history"
#     )

# INVOICES TODO
# getInvoices x
# getInvoice x
# createInvoices x
# updateInvoice
# updateOrCreateInvoices
# getInvoiceAsPdf
# getInvoiceAttachments x
# getInvoiceAttachmentById x
# getInvoiceAttachmentByFileName x
# updateInvoiceAttachmentByFileName x
# createInvoiceAttachmentByFileName x
# getOnlineInvoice
# emailInvoice
# getInvoiceHistory
# createInvoiceHistory
@app.route("/accounting_invoice_read_all")
@xero_token_required
def accounting_invoice_read_all():
    code = get_code_snippet("INVOICES","READ_ALL")

    #[INVOICES:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        invoices_read = accounting_api.get_invoices(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Total invoices found:  {}.".format(len(invoices_read.invoices)
        )
        json = serialize_model(invoices_read)
    #[/INVOICES:READ_ALL]

    return render_template(
        "output.html", title="Invoices",code=code, output=output, json=json, len = 0, set="accounting", endpoint="invoice", action="read_all"
    )

@app.route("/accounting_invoice_read_one")
@xero_token_required
def accounting_invoice_read_one():
    code = get_code_snippet("INVOICES","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_invoices = accounting_api.get_invoices(
            xero_tenant_id
        )
        invoice_id = getvalue(read_invoices, "invoices.0.invoice_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[INVOICES:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_one_invoice = accounting_api.get_invoice(
            xero_tenant_id, invoice_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Invoice read with id {} ".format(
            getvalue(read_invoices, "invoices.0.invoice_id", "")
        )
        json = serialize_model(read_one_invoice)
    #[/INVOICES:READ_ONE]

    return render_template(
        "output.html", title="Invoices", code=code, json=json, output=output, len = 0, set="accounting", endpoint="invoice", action="read_one"
    )

@app.route("/accounting_invoice_create")
@xero_token_required
def accounting_invoice_create():
    code = get_code_snippet("INVOICES","CREATE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    # READ CONTACT
    try:
        read_contacts = accounting_api.get_contacts(
            xero_tenant_id
        )
        contact_id = getvalue(read_contacts, "contacts.0.contact_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    # READ ACCOUNT
    where = "Type==\"SALES\"&&Status==\"ACTIVE\""
    try:
        read_accounts = accounting_api.get_accounts(
            xero_tenant_id, where=where
        )
        account_id = getvalue(read_accounts, "accounts.0.account_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[INVOICES:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    contact = Contact(
        contact_id=contact_id
    )

    line_item = LineItem(
        account_id=account_id,
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
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "New invoices status is '{}'.".format(
            getvalue(created_invoices, "invoices.0.status", "")
        )
        json = serialize_model(created_invoices)
    #[/INVOICES:CREATE]

    return render_template(
        "output.html", title="Invoices", code=code, output=output, json=json, len = 0, set="accounting", endpoint="invoice", action="create"
    )

@app.route("/accounting_invoice_get_attachments")
@xero_token_required
def accounting_invoice_get_attachments():
    code = get_code_snippet("INVOICES","GET_ATTACHMENTS")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_invoices = accounting_api.get_invoices(
            xero_tenant_id
        )
        invoice_id = getvalue(read_invoices, "invoices.0.invoice_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        try:
            include_online = True
            file_name = "helo-heros.jpg"
            path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
            open_file = open(path_to_upload, 'rb')
            body = open_file.read()
            content_type = mimetypes.MimeTypes().guess_type(file_name)[0]
            invoice_attachment_created = accounting_api.create_invoice_attachment_by_file_name(
                xero_tenant_id,
                invoice_id,
                file_name,
                body,
                include_online,
            )
        except AccountingBadRequestException as exception:
            output = "Error: " + exception.reason
            json = jsonify(exception.error_data)

    # GET INVOICE ATTACHMENTS
    #[INVOICES:GET_ATTACHMENTS]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_invoice_attachments = accounting_api.get_invoice_attachments(
            xero_tenant_id, invoice_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Invoice attachments read {} total".format(
            len(read_invoice_attachments.attachments)
        )
        json = serialize_model(read_invoice_attachments)
    #[/INVOICES:GET_ATTACHMENTS]

    return render_template(
        "output.html", title="Invoices", code=code, output=output, json=json, len = 0, set="accounting", endpoint="invoice", action="get_attachments"
    )

@app.route("/accounting_invoice_get_attachment_by_id")
@xero_token_required
def accounting_invoice_get_attachment_by_id():
    code = get_code_snippet("INVOICES","GET_ATTACHMENTS_BY_ID")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_invoices = accounting_api.get_invoices(
            xero_tenant_id
        )
        invoice_id = getvalue(read_invoices, "invoices.0.invoice_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        try:
            include_online = True
            file_name = "helo-heros.jpg"
            path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
            open_file = open(path_to_upload, 'rb')
            body = open_file.read()
            content_type = mimetypes.MimeTypes().guess_type(file_name)[0]
            invoice_attachment_created = accounting_api.create_invoice_attachment_by_file_name(
                xero_tenant_id,
                invoice_id,
                file_name,
                body,
                include_online,
            )
            attachment_id = getvalue(invoice_attachment_created, "attachments.0.attachment_id", "")
        except AccountingBadRequestException as exception:
            output = "Error: " + exception.reason
            json = jsonify(exception.error_data)

    # GET INVOICE ATTACHMENTS
    #[INVOICES:GET_ATTACHMENTS_BY_ID]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_invoice_attachments = accounting_api.get_invoice_attachment_by_id(
            xero_tenant_id, invoice_id, attachment_id, content_type
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Invoice attachment read with ID {} ".format(
            getvalue(read_invoice_attachments, "attachments.0.attachment_id", "")
        )
        json = serialize_model(read_invoice_attachments)
    #[/INVOICES:GET_ATTACHMENTS_BY_ID]

    return render_template(
        "output.html", title="Invoices", code=code, output=output, json=json, len = 0, set="accounting", endpoint="invoice", action="get_attachment_by_id"
    )

@app.route("/accounting_invoice_get_attachment_by_file_name")
@xero_token_required
def accounting_invoice_get_attachment_by_file_name():
    code = get_code_snippet("INVOICES","GET_ATTACHMENT_BY_FILE_NAME")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_invoices = accounting_api.get_invoices(
            xero_tenant_id
        )
        invoice_id = getvalue(read_invoices, "invoices.0.invoice_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        try:
            include_online = True
            file_name = "helo-heros.jpg"
            path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
            open_file = open(path_to_upload, 'rb')
            body = open_file.read()
            content_type = mimetypes.MimeTypes().guess_type(file_name)[0]
            invoice_attachment_created = accounting_api.create_invoice_attachment_by_file_name(
                xero_tenant_id,
                invoice_id,
                file_name,
                body,
            )
            file_name = getvalue(invoice_attachment_created, "attachments.0.file_name", "")
        except AccountingBadRequestException as exception:
            output = "Error: " + exception.reason
            json = jsonify(exception.error_data)

    # GET INVOICE ATTACHMENTS
    #[INVOICES:GET_ATTACHMENT_BY_FILE_NAME]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_invoice_attachments = accounting_api.get_invoice_attachment_by_file_name(
            xero_tenant_id, invoice_id, file_name, content_type
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Invoice attachment read with file name {} ".format(
            getvalue(read_invoice_attachments, "attachments.0.file_name", "")
        )
        json = serialize_model(read_invoice_attachments)
    #[/INVOICES:GET_ATTACHMENT_BY_FILE_NAME]

    return render_template(
        "output.html", title="Invoices", code=code, output=output, json=json, len = 0, set="accounting", endpoint="invoice", action="get_attachment_by_file_name"
    )

@app.route("/accounting_invoice_attachment_create_by_file_name")
@xero_token_required
def accounting_invoice_attachment_create_by_file_name():
    code = get_code_snippet("INVOICEATTACHMENTS","CREATEBYFILENAME")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_invoices = accounting_api.get_invoices(
            xero_tenant_id
        )
        invoice_id = getvalue(read_invoices, "invoices.0.invoice_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[INVOICEATTACHMENTS:CREATEBYFILENAME]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    include_online = True
    file_name = "helo-heros.jpg"
    path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
    open_file = open(path_to_upload, 'rb')
    body = open_file.read()
    content_type = mimetypes.MimeTypes().guess_type(file_name)[0]

    try:
        created_invoice_attachments_by_file_name = accounting_api.create_invoice_attachment_by_file_name(
            xero_tenant_id,
            invoice_id,
            file_name,
            body,
            include_online,
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Invoice attachment created with url {} .".format(
            getvalue(created_invoice_attachments_by_file_name, "attachments.0.url", "")
        )
        json = serialize_model(created_invoice_attachments_by_file_name)
    
    #[/INVOICEATTACHMENTS:CREATEBYFILENAME]

    return render_template(
        "output.html", title="Invoices", code=code, output=output, json=json, len = 0, set="accounting", endpoint="invoice", action="create_attachment_by_file_name"
    )

@app.route("/accounting_invoice_update_attachment")
@xero_token_required
def accounting_invoice_update_attachment():
    code = get_code_snippet("ACCOUNTS","UPDATE_ATTACHMENT")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_invoices = accounting_api.get_invoices(
            xero_tenant_id
        )
        invoice_id = getvalue(read_invoices, "invoices.0.invoice_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        try:
            include_online = True
            file_name = "helo-heros.jpg"
            path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
            open_file = open(path_to_upload, 'rb')
            body = open_file.read()
            content_type = mimetypes.MimeTypes().guess_type(file_name)[0]
            invoice_attachment_created = accounting_api.create_invoice_attachment_by_file_name(
                xero_tenant_id,
                invoice_id,
                file_name,
                body,
                include_online,
            )
            file_name = getvalue(invoice_attachment_created, "attachments.0.file_name", "")
        except AccountingBadRequestException as exception:
            output = "Error: " + exception.reason
            json = jsonify(exception.error_data)

    # UPDATE INVOICE ATTACHMENT
    #[INVOICES:UPDATE_ATTACHMENT]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        include_online = True
        file_name = file_name
        path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
        open_file = open(path_to_upload, 'rb')
        body = open_file.read()
        content_type = mimetypes.MimeTypes().guess_type(file_name)[0]
        invoice_attachment_updated = accounting_api.update_invoice_attachment_by_file_name(
            xero_tenant_id,
            invoice_id,
            file_name,
            body,
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Attachment name '{}' updated.".format(
            getvalue(invoice_attachment_updated, "attachments.0.file_name", "")
        )
        json = serialize_model(invoice_attachment_updated)
    #[/INVOICES:UPDATE_ATTACHMENT]

    return render_template(
        "output.html", title="Invoices", code=code, output=output, json=json, len = 0, set="accounting", endpoint="invoice", action="update_attachment"
    )

# @app.route("/accounting_bank_transaction_history_read")
# @xero_token_required
# def accounting_bank_transaction_history_read():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","READ")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:READ]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transaction_history = accounting_api.get_bank_transactions_history(
#             xero_tenant_id, bank_transaction_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank Transaction History read {} total".format(
#             len(read_bank_transaction_history.history_records)
#         )
#         json = serialize_model(read_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:READ]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="read_history"
#     )

# @app.route("/accounting_bank_transaction_history_create")
# @xero_token_required
# def accounting_bank_transaction_history_create():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","CREATE")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:CREATE]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     history_record = HistoryRecord(
#         details = "I'm a history record " + get_random_num()
#     )

#     history_records = HistoryRecords(
#         history_records = [history_record]
#     )

#     try:
#         create_bank_transaction_history = accounting_api.create_bank_transaction_history_record(
#             xero_tenant_id, bank_transaction_id, history_records
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank transaction history added with details {} .".format(
#             getvalue(create_bank_transaction_history, "history_records.0.details", "")
#         )
#         json = serialize_model(create_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:CREATE]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="create_history"
#     )

# INVOICE REMINDERS
# getInvoiceReminders x

@app.route("/accounting_invoice_reminder_read_all")
@xero_token_required
def accounting_invoice_reminder_read_all():
    code = get_code_snippet("INVOICEREMINDERS","READ_ALL")

    #[INVOICEREMINDERS:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_invoice_reminders = accounting_api.get_invoice_reminders(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Invoice Reminders read {} total".format(
            len(read_invoice_reminders.invoice_reminders)
        )
        json = serialize_model(read_invoice_reminders)
    #[/INVOICEREMINDERS:READ_ALL]

    return render_template(
        "output.html", title="Invoice Reminders", code=code, json=json, output=output, len = 0, set="accounting", endpoint="invoice_reminder", action="read_all"
    )

# ITEMS TODO
# getItems x
# createItems x
# updateOrCreateItems
# getItem x
# updateItem
# deleteItem
# getItemHistory
# createItemHistory

@app.route("/accounting_item_read_all")
@xero_token_required
def accounting_item_read_all():
    code = get_code_snippet("ITEMS","READ_ALL")

    #[ITEMS:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_items = accounting_api.get_items(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Items read {} total".format(
            len(read_items.items)
        )
        json = serialize_model(read_items)
    #[/ITEMS:READ_ALL]

    return render_template(
        "output.html", title="Items", code=code, json=json, output=output, len = 0, set="accounting", endpoint="item", action="read_all"
    )

@app.route("/accounting_item_read_one")
@xero_token_required
def accounting_item_read_one():
    code = get_code_snippet("ITEMS","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_items = accounting_api.get_items(
            xero_tenant_id
        )
        item_id = getvalue(read_items, "items.0.item_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[ITEMS:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_one_item = accounting_api.get_item(
            xero_tenant_id, item_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Item read with id {} ".format(
            getvalue(read_items, "items.0.item_id", "")
        )
        json = serialize_model(read_one_item)
    #[/ITEMS:READ_ONE]

    return render_template(
        "output.html", title="Items", code=code, json=json, output=output, len = 0, set="accounting", endpoint="item", action="read_one"
    )

@app.route("/accounting_item_create")
@xero_token_required
def accounting_item_create():
    code = get_code_snippet("ITEMS","CREATE")

    #[ITEMS:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    purchase_details = Purchase(
        unit_price=375.5000,
        tax_type="NONE",
        account_code="500"
    )

    sales_details = Purchase(
        unit_price=520.9900,
        tax_type="NONE",
        account_code="400"
    )

    item = Item(
        code="Foo"+get_random_num(),
        name="Bar",
        purchase_details=purchase_details,
        sales_details=sales_details
    )

    items = Items(items=[item])

    try:
        created_item = accounting_api.create_items(
            xero_tenant_id, items
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Item created with id {} .".format(
            getvalue(created_item, "items.0.item_id", "")
        )
        json = serialize_model(created_item)
    #[/ITEMS:CREATE]

    return render_template(
        "output.html", title="Items", code=code, json=json, output=output, len = 0, set="accounting", endpoint="item", action="create"
    )

# @app.route("/accounting_bank_transaction_history_read")
# @xero_token_required
# def accounting_bank_transaction_history_read():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","READ")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:READ]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transaction_history = accounting_api.get_bank_transactions_history(
#             xero_tenant_id, bank_transaction_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank Transaction History read {} total".format(
#             len(read_bank_transaction_history.history_records)
#         )
#         json = serialize_model(read_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:READ]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="read_history"
#     )

# @app.route("/accounting_bank_transaction_history_create")
# @xero_token_required
# def accounting_bank_transaction_history_create():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","CREATE")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:CREATE]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     history_record = HistoryRecord(
#         details = "I'm a history record " + get_random_num()
#     )

#     history_records = HistoryRecords(
#         history_records = [history_record]
#     )

#     try:
#         create_bank_transaction_history = accounting_api.create_bank_transaction_history_record(
#             xero_tenant_id, bank_transaction_id, history_records
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank transaction history added with details {} .".format(
#             getvalue(create_bank_transaction_history, "history_records.0.details", "")
#         )
#         json = serialize_model(create_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:CREATE]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="create_history"
#     )

# JOURNALS
# getJournals x
# getJournal x
@app.route("/accounting_journals_read_all")
@xero_token_required
def accounting_journals_read_all():
    code = get_code_snippet("JOURNALS","READ_ALL")

    #[JOURNALS:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_journals = accounting_api.get_journals(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Journals read {} total".format(
            len(read_journals.journals)
        )
        json = serialize_model(read_journals)
    #[/JOURNALS:READ_ALL]

    return render_template(
        "output.html", title="Journals", code=code, json=json, output=output, len = 0, set="accounting", endpoint="journals", action="read_all"
    )

@app.route("/accounting_journals_read_one")
@xero_token_required
def accounting_journals_read_one():
    code = get_code_snippet("JOURNAL","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_journals = accounting_api.get_journals(
            xero_tenant_id
        )
        journal_id = getvalue(read_journals, "journals.0.journal_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[JOURNAL:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_one_journal = accounting_api.get_journal(
            xero_tenant_id, journal_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Journal read with id {} ".format(
            getvalue(read_journals, "journals.0.journal_id", "")
        )
        json = serialize_model(read_one_journal)
    #[/JOURNAL:READ_ONE]

    return render_template(
        "output.html", title="Journals", code=code, json=json, output=output, len = 0, set="accounting", endpoint="journals", action="read_one"
    )

@app.route("/accounting_journals_read_one_by_number")
@xero_token_required
def accounting_journals_read_one_by_number():
    code = get_code_snippet("JOURNAL","READ_ONE_BY_NUMBER")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_journals = accounting_api.get_journals(
            xero_tenant_id
        )
        journal_number = getvalue(read_journals, "journals.0.journal_number", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[JOURNAL:READ_ONE_BY_NUMBER]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_one_journal = accounting_api.get_journal_by_number(
            xero_tenant_id, journal_number
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Journal read with number {} ".format(
            getvalue(read_journals, "journals.0.journal_number", "")
        )
        json = serialize_model(read_one_journal)
    #[/JOURNAL:READ_ONE_BY_NUMBER]

    return render_template(
        "output.html", title="Journals", code=code, json=json, output=output, len = 0, set="accounting", endpoint="journals", action="read_one_by_number"
    )

# LINKED TRANSACTIONS TODO
# getLinkedTransactions x
# createLinkedTransaction
# getLinkedTransaction x
# updateLinkedTransaction
# deleteLinkedTransaction
@app.route("/accounting_linked_transactions_read_all")
@xero_token_required
def accounting_linked_transactions_read_all():
    code = get_code_snippet("LINKED_TRANSACTIONS","READ_ALL")

    #[LINKED_TRANSACTIONS:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_linked_transactions = accounting_api.get_linked_transactions(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Linked Transactions read {} total".format(
            len(read_linked_transactions.linked_transactions)
        )
        json = serialize_model(read_linked_transactions)
    #[/LINKED_TRANSACTIONS:READ_ALL]

    return render_template(
        "output.html", title="Linked Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="linked_transactions", action="read_all"
    )

@app.route("/accounting_linked_transactions_read_one")
@xero_token_required
def accounting_linked_transactions_read_one():
    code = get_code_snippet("LINKED_TRANSACTIONS","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_linked_transactions = accounting_api.get_linked_transactions(
            xero_tenant_id
        )
        linked_transaction_id = getvalue(read_linked_transactions, "linked_transactions.0.linked_transaction_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[LINKED_TRANSACTIONS:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_one_linked_transaction = accounting_api.get_linked_transaction(
            xero_tenant_id, linked_transaction_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Linked Transaction read with id {} ".format(
            getvalue(read_linked_transactions, "linked_transactions.0.linked_transaction_id", "")
        )
        json = serialize_model(read_one_linked_transaction)
    #[/LINKED_TRANSACTIONS:READ_ONE]

    return render_template(
        "output.html", title="Linked Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="linked_transactions", action="read_one"
    )

# MANUAL JOURNALS TODO
# getManualJournals x
# createManualJournals
# updateOrCreateManualJournals
# getManualJournal x
# updateManualJournal
# getManualJournalAttachments
# getManualJournalAttachmentById
# getManualJournalAttachmentByFileName
# updateManualJournalAttachmentByFileName
# createManualJournalAttachmentByFileName
@app.route("/accounting_manual_journals_read_all")
@xero_token_required
def accounting_manual_journals_read_all():
    code = get_code_snippet("MANUAL_JOURNALS","READ_ALL")

    #[MANUAL_JOURNALS:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_manual_journals = accounting_api.get_manual_journals(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Manual Journals read {} total".format(
            len(read_manual_journals.manual_journals)
        )
        json = serialize_model(read_manual_journals)
    #[/MANUAL_JOURNALS:READ_ALL]

    return render_template(
        "output.html", title="Manual Journals", code=code, json=json, output=output, len = 0, set="accounting", endpoint="manual_journals", action="read_all"
    )

@app.route("/accounting_manual_journals_read_one")
@xero_token_required
def accounting_manual_journals_read_one():
    code = get_code_snippet("MANUAL_JOURNALS","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_manual_journals = accounting_api.get_manual_journals(
            xero_tenant_id
        )
        manual_journal_id = getvalue(read_manual_journals, "manual_journals.0.manual_journal_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[MANUAL_JOURNALS:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_one_manual_journal = accounting_api.get_manual_journal(
            xero_tenant_id, manual_journal_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Manual Journal read with id {} ".format(
            getvalue(read_manual_journals, "manual_journals.0.manual_journal_id", "")
        )
        json = serialize_model(read_one_manual_journal)
    #[/MANUAL_JOURNALS:READ_ONE]

    return render_template(
        "output.html", title="Manual Journals", code=code, json=json, output=output, len = 0, set="accounting", endpoint="manual_journals", action="read_one"
    )

# @app.route("/accounting_account_get_attachments")
# @xero_token_required
# def accounting_account_get_attachments():
#     code = get_code_snippet("ACCOUNTS","GET_ATTACHMENTS")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     # CREATE ACCOUNT
#     account = Account(
#         name="FooBar" + get_random_num(),
#         code=get_random_num(),
#         description="My Foobar",
#         type=AccountType.EXPENSE,
#     )

#     try:
#         created_accounts = accounting_api.create_account(
#             xero_tenant_id, account
#         )
#         account_id = getvalue(created_accounts, "accounts.0.account_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         try:
#             include_online = True
#             myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
#             with myimage.open("rb") as image:
#                 account_attachment_created = accounting_api.create_account_attachment_by_file_name(
#                     xero_tenant_id,
#                     account_id,
#                     file_name=myimage.name,
#                     body=image.read(),
#                 )
#         except AccountingBadRequestException as exception:
#             output = "Error: " + exception.reason
#             json = jsonify(exception.error_data)

#     # GET ACCOUNT ATTACHMENTS
#     #[ACCOUNTS:GET_ATTACHMENTS]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_account_attachments = accounting_api.get_account_attachments(
#             xero_tenant_id, account_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Account attachments read {} total".format(
#             len(read_account_attachments.attachments)
#         )
#         json = serialize_model(read_account_attachments)
#     #[/ACCOUNTS:GET_ATTACHMENTS]

#     return render_template(
#         "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="get_attachments"
#     )

# @app.route("/accounting_account_get_attachment_by_id")
# @xero_token_required
# def accounting_account_get_attachment_by_id():
#     code = get_code_snippet("ACCOUNTS","GET_ATTACHMENTS")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     # CREATE ACCOUNT
#     account = Account(
#         name="FooBar" + get_random_num(),
#         code=get_random_num(),
#         description="My Foobar",
#         type=AccountType.EXPENSE,
#     )

#     try:
#         created_accounts = accounting_api.create_account(
#             xero_tenant_id, account
#         )
#         account_id = getvalue(created_accounts, "accounts.0.account_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         try:
#             include_online = True
#             myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
#             with myimage.open("rb") as image:
#                 account_attachment_created = accounting_api.create_account_attachment_by_file_name(
#                     xero_tenant_id,
#                     account_id,
#                     file_name=myimage.name,
#                     body=image.read(),
#                 )
#         except AccountingBadRequestException as exception:
#             output = "Error: " + exception.reason
#             json = jsonify(exception.error_data)

#     # GET ACCOUNT ATTACHMENTS
#     #[ACCOUNTS:GET_ATTACHMENTS]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_account_attachments = accounting_api.get_account_attachments(
#             xero_tenant_id, account_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Account attachments read {} total".format(
#             len(read_account_attachments.attachments)
#         )
#         json = serialize_model(read_account_attachments)
#     #[/ACCOUNTS:GET_ATTACHMENTS]

#     return render_template(
#         "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="get_attachments"
#     )

# @app.route("/accounting_account_get_attachment_by_file_name")
# @xero_token_required
# def accounting_account_get_attachment_by_file_name():
#     code = get_code_snippet("ACCOUNTS","GET_ATTACHMENTS")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     # CREATE ACCOUNT
#     account = Account(
#         name="FooBar" + get_random_num(),
#         code=get_random_num(),
#         description="My Foobar",
#         type=AccountType.EXPENSE,
#     )

#     try:
#         created_accounts = accounting_api.create_account(
#             xero_tenant_id, account
#         )
#         account_id = getvalue(created_accounts, "accounts.0.account_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         try:
#             include_online = True
#             myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
#             with myimage.open("rb") as image:
#                 account_attachment_created = accounting_api.create_account_attachment_by_file_name(
#                     xero_tenant_id,
#                     account_id,
#                     file_name=myimage.name,
#                     body=image.read(),
#                 )
#         except AccountingBadRequestException as exception:
#             output = "Error: " + exception.reason
#             json = jsonify(exception.error_data)

#     # GET ACCOUNT ATTACHMENTS
#     #[ACCOUNTS:GET_ATTACHMENTS]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_account_attachments = accounting_api.get_account_attachments(
#             xero_tenant_id, account_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Account attachments read {} total".format(
#             len(read_account_attachments.attachments)
#         )
#         json = serialize_model(read_account_attachments)
#     #[/ACCOUNTS:GET_ATTACHMENTS]

#     return render_template(
#         "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="get_attachments"
#     )

# @app.route("/accounting_bank_transaction_attachment_create_by_file_name")
# @xero_token_required
# def accounting_bank_transaction_attachment_create_by_file_name():
#     code = get_code_snippet("BANKTRANSACTIONATTACHMENTS","CREATEBYFILENAME")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONATTACHMENTS:CREATEBYFILENAME]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     file_name = "helo-heros.jpg"
#     path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
#     open_file = open(path_to_upload, 'rb')
#     body = open_file.read()

#     try:
#         created_bank_transaction_attachments_by_file_name = accounting_api.create_bank_transaction_attachment_by_file_name(
#             xero_tenant_id, bank_transaction_id, file_name, body
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank transaction attachment created with url {} .".format(
#             getvalue(created_bank_transaction_attachments_by_file_name, "attachments.0.url", "")
#         )
#         json = serialize_model(created_bank_transaction_attachments_by_file_name)
    
#     #[/BANKTRANSACTIONATTACHMENTS:CREATEBYFILENAME]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, output=output, json=json, len = 0, set="accounting", endpoint="bank_transaction", action="create_attachment_by_file_name"
#     )

# @app.route("/accounting_account_update_attachment")
# @xero_token_required
# def accounting_account_update_attachment():
#     code = get_code_snippet("ACCOUNTS","CREATE_ATTACHMENT")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     # CREATE ACCOUNT
#     account = Account(
#         name="FooBar" + get_random_num(),
#         code=get_random_num(),
#         description="My Foobar",
#         type=AccountType.EXPENSE,
#     )

#     try:
#         created_accounts = accounting_api.create_account(
#             xero_tenant_id, account
#         )
#         account_id = getvalue(created_accounts, "accounts.0.account_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     # CREATE ACCOUNT ATTACHMENT
#     #[ACCOUNTS:CREATE_ATTACHMENT]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         include_online = True
#         myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
#         with myimage.open("rb") as image:
#             account_attachment_created = accounting_api.create_account_attachment_by_file_name(
#                 xero_tenant_id,
#                 account_id,
#                 file_name=myimage.name,
#                 body=image.read(),
#             )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Attachment url '{}' created.".format(
#             getvalue(account_attachment_created, "attachments.0.url", "")
#         )
#         json = serialize_model(account_attachment_created)
#     #[/ACCOUNTS:CREATE_ATTACHMENT]

#     return render_template(
#         "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="create_attachment"
#     )

# ORGANISATION TODO
# getOrganisations x
# getOrganisationCISSettings
@app.route("/accounting_organisations_read_all")
@xero_token_required
def accounting_organisations_read_all():
    code = get_code_snippet("ORGANISATIONS","READ_ALL")

    #[ORGANISATIONS:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_organisations = accounting_api.get_organisations(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Organisations read {} total".format(
            len(read_organisations.organisations)
        )
        json = serialize_model(read_organisations)
    #[/ORGANISATIONS:READ_ALL]

    return render_template(
        "output.html", title="Organisations", code=code, json=json, output=output, len = 0, set="accounting", endpoint="organisations", action="read_all"
    )

# OVERPAYMENTS TODO
# getOverpayments x
# getOverpayment x
# createOverpaymentAllocations
# getOverpaymentHistory
# createOverpaymentHistory
@app.route("/accounting_overpayments_read_all")
@xero_token_required
def accounting_overpayments_read_all():
    code = get_code_snippet("OVERPAYMENTS","READ_ALL")

    #[OVERPAYMENTS:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_overpayments = accounting_api.get_overpayments(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Overpayments read {} total".format(
            len(read_overpayments.overpayments)
        )
        json = serialize_model(read_overpayments)
    #[/OVERPAYMENTS:READ_ALL]

    return render_template(
        "output.html", title="Overpayments", code=code, json=json, output=output, len = 0, set="accounting", endpoint="overpayments", action="read_all"
    )

@app.route("/accounting_overpayments_read_one")
@xero_token_required
def accounting_overpayments_read_one():
    code = get_code_snippet("OVERPAYMENTS","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_overpayments = accounting_api.get_overpayments(
            xero_tenant_id
        )
        overpayment_id = getvalue(read_overpayments, "overpayments.0.overpayment_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[OVERPAYMENTS:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_one_overpayment = accounting_api.get_overpayment(
            xero_tenant_id, overpayment_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Overpayment read with id {} ".format(
            getvalue(read_overpayments, "overpayments.0.overpayment_id", "")
        )
        json = serialize_model(read_one_overpayment)
    #[/OVERPAYMENTS:READ_ONE]

    return render_template(
        "output.html", title="Overpayments", code=code, json=json, output=output, len = 0, set="accounting", endpoint="overpayments", action="read_one"
    )

# @app.route("/accounting_bank_transaction_history_read")
# @xero_token_required
# def accounting_bank_transaction_history_read():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","READ")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:READ]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transaction_history = accounting_api.get_bank_transactions_history(
#             xero_tenant_id, bank_transaction_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank Transaction History read {} total".format(
#             len(read_bank_transaction_history.history_records)
#         )
#         json = serialize_model(read_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:READ]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="read_history"
#     )

# @app.route("/accounting_bank_transaction_history_create")
# @xero_token_required
# def accounting_bank_transaction_history_create():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","CREATE")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:CREATE]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     history_record = HistoryRecord(
#         details = "I'm a history record " + get_random_num()
#     )

#     history_records = HistoryRecords(
#         history_records = [history_record]
#     )

#     try:
#         create_bank_transaction_history = accounting_api.create_bank_transaction_history_record(
#             xero_tenant_id, bank_transaction_id, history_records
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank transaction history added with details {} .".format(
#             getvalue(create_bank_transaction_history, "history_records.0.details", "")
#         )
#         json = serialize_model(create_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:CREATE]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="create_history"
#     )

# PAYMENTS TODO
# getPayments x
# createPayments
# createPayment
# getPayment x
# deletePayment
# getPaymentHistory
# createPaymentHistory
@app.route("/accounting_payments_read_all")
@xero_token_required
def accounting_payments_read_all():
    code = get_code_snippet("PAYMENTS","READ_ALL")

    #[PAYMENTS:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_payments = accounting_api.get_payments(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Payments read {} total".format(
            len(read_payments.payments)
        )
        json = serialize_model(read_payments)
    #[/PAYMENTS:READ_ALL]

    return render_template(
        "output.html", title="Payments", code=code, json=json, output=output, len = 0, set="accounting", endpoint="payments", action="read_all"
    )

@app.route("/accounting_payments_read_one")
@xero_token_required
def accounting_payments_read_one():
    code = get_code_snippet("PAYMENTS","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_payments = accounting_api.get_payments(
            xero_tenant_id
        )
        payment_id = getvalue(read_payments, "payments.0.payment_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[PAYMENTS:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_one_payment = accounting_api.get_payment(
            xero_tenant_id, payment_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Payment read with id {} ".format(
            getvalue(read_payments, "payments.0.payment_id", "")
        )
        json = serialize_model(read_one_payment)
    #[/PAYMENTS:READ_ONE]

    return render_template(
        "output.html", title="Payments", code=code, json=json, output=output, len = 0, set="accounting", endpoint="payments", action="read_one"
    )

# @app.route("/accounting_bank_transaction_history_read")
# @xero_token_required
# def accounting_bank_transaction_history_read():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","READ")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:READ]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transaction_history = accounting_api.get_bank_transactions_history(
#             xero_tenant_id, bank_transaction_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank Transaction History read {} total".format(
#             len(read_bank_transaction_history.history_records)
#         )
#         json = serialize_model(read_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:READ]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="read_history"
#     )

# @app.route("/accounting_bank_transaction_history_create")
# @xero_token_required
# def accounting_bank_transaction_history_create():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","CREATE")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:CREATE]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     history_record = HistoryRecord(
#         details = "I'm a history record " + get_random_num()
#     )

#     history_records = HistoryRecords(
#         history_records = [history_record]
#     )

#     try:
#         create_bank_transaction_history = accounting_api.create_bank_transaction_history_record(
#             xero_tenant_id, bank_transaction_id, history_records
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank transaction history added with details {} .".format(
#             getvalue(create_bank_transaction_history, "history_records.0.details", "")
#         )
#         json = serialize_model(create_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:CREATE]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="create_history"
#     )

# PAYMENT SERVICES
# getPaymentServices x
# createPaymentService x
@app.route("/accounting_payment_services_read_all")
@xero_token_required
def accounting_payment_services_read_all():
    code = get_code_snippet("PAYMENT_SERVICES","READ_ALL")

    #[PAYMENT_SERVICES:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_payment_services = accounting_api.get_payment_services(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Payment Services read {} total".format(
            len(read_payment_services.payment_services)
        )
        json = serialize_model(read_payment_services)
    #[/PAYMENT_SERVICES:READ_ALL]

    return render_template(
        "output.html", title="Payment Services", code=code, json=json, output=output, len = 0, set="accounting", endpoint="payment_services", action="read_all"
    )

@app.route("/accounting_payment_service_create")
@xero_token_required
def accounting_payment_service_create():
    code = get_code_snippet("PAYMENTSERVICES","CREATE")

    #[PAYMENTSERVICES:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    payment_service = PaymentService(
        payment_service_name="PayUpNow " + get_random_num(),
        payment_service_url="https://www.payupnow.com/?invoiceNo=[INVOICENUMBER]&currency=[CURRENCY]&amount=[AMOUNTDUE]&shortCode=[SHORTCODE]",
        pay_now_text="Time To Pay"
    )

    payment_services = PaymentServices(payment_services=[payment_service])

    try:
        created_payment_services = accounting_api.create_payment_service(
            xero_tenant_id, payment_services
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Payment service created with id {} .".format(
            getvalue(created_payment_services, "payment_services.0.payment_service_id", "")
        )
        json = serialize_model(created_payment_services)
    #[/PAYMENTSERVICES:CREATE]

    return render_template(
        "output.html", title="Payment Services", code=code, json=json, output=output, len = 0, set="accounting", endpoint="payment_service", action="create"
    )

# PREPAYMENTS TODO
# getPrepayments x
# getPrepayment x
# createPrepaymentAllocations
# getPrepaymentHistory
# createPrepaymentHistory
@app.route("/accounting_prepayments_read_all")
@xero_token_required
def accounting_prepayments_read_all():
    code = get_code_snippet("PREPAYMENTS","READ_ALL")

    #[PREPAYMENTS:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_prepayments = accounting_api.get_prepayments(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Prepayments read {} total".format(
            len(read_prepayments.prepayments)
        )
        json = serialize_model(read_prepayments)
    #[/PREPAYMENTS:READ_ALL]

    return render_template(
        "output.html", title="Prepayments", code=code, json=json, output=output, len = 0, set="accounting", endpoint="prepayments", action="read_all"
    )

@app.route("/accounting_prepayments_read_one")
@xero_token_required
def accounting_prepayments_read_one():
    code = get_code_snippet("PREPAYMENTS","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_prepayments = accounting_api.get_prepayments(
            xero_tenant_id
        )
        prepayment_id = getvalue(read_prepayments, "prepayments.0.prepayment_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[PREPAYMENTS:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_one_prepayment = accounting_api.get_prepayment(
            xero_tenant_id, prepayment_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Prepayment read with id {} ".format(
            getvalue(read_prepayments, "prepayments.0.prepayment_id", "")
        )
        json = serialize_model(read_one_prepayment)
    #[/PREPAYMENTS:READ_ONE]

    return render_template(
        "output.html", title="Prepayments", code=code, json=json, output=output, len = 0, set="accounting", endpoint="prepayments", action="read_one"
    )

# @app.route("/accounting_bank_transaction_history_read")
# @xero_token_required
# def accounting_bank_transaction_history_read():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","READ")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:READ]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transaction_history = accounting_api.get_bank_transactions_history(
#             xero_tenant_id, bank_transaction_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank Transaction History read {} total".format(
#             len(read_bank_transaction_history.history_records)
#         )
#         json = serialize_model(read_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:READ]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="read_history"
#     )

# @app.route("/accounting_bank_transaction_history_create")
# @xero_token_required
# def accounting_bank_transaction_history_create():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","CREATE")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:CREATE]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     history_record = HistoryRecord(
#         details = "I'm a history record " + get_random_num()
#     )

#     history_records = HistoryRecords(
#         history_records = [history_record]
#     )

#     try:
#         create_bank_transaction_history = accounting_api.create_bank_transaction_history_record(
#             xero_tenant_id, bank_transaction_id, history_records
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank transaction history added with details {} .".format(
#             getvalue(create_bank_transaction_history, "history_records.0.details", "")
#         )
#         json = serialize_model(create_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:CREATE]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="create_history"
#     )

# PURCHASE ORDERS TODO
# getPurchaseOrders x
# createPurchaseOrders
# updateOrCreatePurchaseOrders
# getPurchaseOrderAsPdf
# getPurchaseOrder
# updatePurchaseOrder
# getPurchaseOrderByNumber
# getPurchaseOrderHistory
# createPurchaseOrderHistory
@app.route("/accounting_purchase_orders_read_all")
@xero_token_required
def accounting_purchase_orders_read_all():
    code = get_code_snippet("PURCHASE_ORDERS","READ_ALL")

    #[PURCHASE_ORDERS:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_purchase_orders = accounting_api.get_purchase_orders(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Purchase Orders read {} total".format(
            len(read_purchase_orders.purchase_orders)
        )
        json = serialize_model(read_purchase_orders)
    #[/PURCHASE_ORDERS:READ_ALL]

    return render_template(
        "output.html", title="Purchase Orders", code=code, json=json, output=output, len = 0, set="accounting", endpoint="purchase_orders", action="read_all"
    )

@app.route("/accounting_purchase_orders_read_one")
@xero_token_required
def accounting_purchase_orders_read_one():
    code = get_code_snippet("PURCHASE_ORDERS","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_purchase_orders = accounting_api.get_purchase_orders(
            xero_tenant_id
        )
        purchase_order_id = getvalue(read_purchase_orders, "purchase_orders.0.purchase_order_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[PURCHASE_ORDERS:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_one_purchase_order = accounting_api.get_purchase_order(
            xero_tenant_id, purchase_order_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Purchase Order read with id {} ".format(
            getvalue(read_purchase_orders, "purchase_orders.0.purchase_order_id", "")
        )
        json = serialize_model(read_one_purchase_order)
    #[/PURCHASE_ORDERS:READ_ONE]

    return render_template(
        "output.html", title="Purchase Orders", code=code, json=json, output=output, len = 0, set="accounting", endpoint="purchase_orders", action="read_one"
    )

# @app.route("/accounting_bank_transaction_history_read")
# @xero_token_required
# def accounting_bank_transaction_history_read():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","READ")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:READ]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transaction_history = accounting_api.get_bank_transactions_history(
#             xero_tenant_id, bank_transaction_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank Transaction History read {} total".format(
#             len(read_bank_transaction_history.history_records)
#         )
#         json = serialize_model(read_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:READ]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="read_history"
#     )

# @app.route("/accounting_bank_transaction_history_create")
# @xero_token_required
# def accounting_bank_transaction_history_create():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","CREATE")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:CREATE]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     history_record = HistoryRecord(
#         details = "I'm a history record " + get_random_num()
#     )

#     history_records = HistoryRecords(
#         history_records = [history_record]
#     )

#     try:
#         create_bank_transaction_history = accounting_api.create_bank_transaction_history_record(
#             xero_tenant_id, bank_transaction_id, history_records
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank transaction history added with details {} .".format(
#             getvalue(create_bank_transaction_history, "history_records.0.details", "")
#         )
#         json = serialize_model(create_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:CREATE]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="create_history"
#     )

# QUOTES TODO
# getQuotes x
# createQuotes
# updateOrCreateQuotes
# getQuote x
# updateQuote
# getQuoteHistory
# createQuoteHistory
# getQuoteAsPdf
# getQuoteAttachments
# getQuoteAttachmentById
# getQuoteAttachmentByFileName
# updateQuoteAttachmentByFileName
# createQuoteAttachmentByFileName
@app.route("/accounting_quotes_read_all")
@xero_token_required
def accounting_quotes_read_all():
    code = get_code_snippet("QUOTES","READ_ALL")

    #[QUOTES:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_quotes = accounting_api.get_quotes(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Quotes read {} total".format(
            len(read_quotes.quotes)
        )
        json = serialize_model(read_quotes)
    #[/QUOTES:READ_ALL]

    return render_template(
        "output.html", title="Quotes", code=code, json=json, output=output, len = 0, set="accounting", endpoint="quotes", action="read_all"
    )

@app.route("/accounting_quotes_read_one")
@xero_token_required
def accounting_quotes_read_one():
    code = get_code_snippet("QUOTES","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_quotes = accounting_api.get_quotes(
            xero_tenant_id
        )
        quote_id = getvalue(read_quotes, "quotes.0.quote_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[QUOTES:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_one_quote = accounting_api.get_quote(
            xero_tenant_id, quote_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Quote read with id {} ".format(
            getvalue(read_quotes, "quotes.0.quote_id", "")
        )
        json = serialize_model(read_one_quote)
    #[/QUOTES:READ_ONE]

    return render_template(
        "output.html", title="Quotes", code=code, json=json, output=output, len = 0, set="accounting", endpoint="quotes", action="read_one"
    )

@app.route("/accounting_quotes_create")
@xero_token_required
def accounting_quotes_create():
    code = get_code_snippet("QUOTES","CREATE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    # READ CONTACT
    try:
        read_contacts = accounting_api.get_contacts(
            xero_tenant_id
        )
        contact_id = getvalue(read_contacts, "contacts.0.contact_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    # READ ACCOUNT
    where = "Type==\"SALES\"&&Status==\"ACTIVE\""
    try:
        read_accounts = accounting_api.get_accounts(
            xero_tenant_id, where=where
        )
        account_id = getvalue(read_accounts, "accounts.0.account_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[QUOTES:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    contact = Contact(
        contact_id=contact_id
    )

    line_item = LineItem(
        account_id=account_id,
        description= "Consulting",
    )

    quote = Quote(
        line_items=[line_item],
        contact=contact,
        date= dateutil.parser.parse("2022-08-29T00:00:00Z"),
    )

    quotes = Quotes(quotes=[quote])

    try:
        created_quotes = accounting_api.create_quotes(
            xero_tenant_id, quotes=quotes
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "New quote created with ID: '{}'.".format(
            getvalue(created_quotes, "quotes.0.quote_id", "")
        )
        json = serialize_model(created_quotes)
    #[/QUOTES:CREATE]

    return render_template(
        "output.html", title="Quotes", code=code, output=output, json=json, len = 0, set="accounting", endpoint="quotes", action="create"
    )

# @app.route("/accounting_bank_transaction_history_create")
# @xero_token_required
# def accounting_bank_transaction_history_create():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","CREATE")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:CREATE]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     history_record = HistoryRecord(
#         details = "I'm a history record " + get_random_num()
#     )

#     history_records = HistoryRecords(
#         history_records = [history_record]
#     )

#     try:
#         create_bank_transaction_history = accounting_api.create_bank_transaction_history_record(
#             xero_tenant_id, bank_transaction_id, history_records
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank transaction history added with details {} .".format(
#             getvalue(create_bank_transaction_history, "history_records.0.details", "")
#         )
#         json = serialize_model(create_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:CREATE]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="create_history"
#     )

# @app.route("/accounting_account_get_attachments")
# @xero_token_required
# def accounting_account_get_attachments():
#     code = get_code_snippet("ACCOUNTS","GET_ATTACHMENTS")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     # CREATE ACCOUNT
#     account = Account(
#         name="FooBar" + get_random_num(),
#         code=get_random_num(),
#         description="My Foobar",
#         type=AccountType.EXPENSE,
#     )

#     try:
#         created_accounts = accounting_api.create_account(
#             xero_tenant_id, account
#         )
#         account_id = getvalue(created_accounts, "accounts.0.account_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         try:
#             include_online = True
#             myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
#             with myimage.open("rb") as image:
#                 account_attachment_created = accounting_api.create_account_attachment_by_file_name(
#                     xero_tenant_id,
#                     account_id,
#                     file_name=myimage.name,
#                     body=image.read(),
#                 )
#         except AccountingBadRequestException as exception:
#             output = "Error: " + exception.reason
#             json = jsonify(exception.error_data)

#     # GET ACCOUNT ATTACHMENTS
#     #[ACCOUNTS:GET_ATTACHMENTS]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_account_attachments = accounting_api.get_account_attachments(
#             xero_tenant_id, account_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Account attachments read {} total".format(
#             len(read_account_attachments.attachments)
#         )
#         json = serialize_model(read_account_attachments)
#     #[/ACCOUNTS:GET_ATTACHMENTS]

#     return render_template(
#         "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="get_attachments"
#     )

# @app.route("/accounting_account_get_attachment_by_id")
# @xero_token_required
# def accounting_account_get_attachment_by_id():
#     code = get_code_snippet("ACCOUNTS","GET_ATTACHMENTS")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     # CREATE ACCOUNT
#     account = Account(
#         name="FooBar" + get_random_num(),
#         code=get_random_num(),
#         description="My Foobar",
#         type=AccountType.EXPENSE,
#     )

#     try:
#         created_accounts = accounting_api.create_account(
#             xero_tenant_id, account
#         )
#         account_id = getvalue(created_accounts, "accounts.0.account_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         try:
#             include_online = True
#             myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
#             with myimage.open("rb") as image:
#                 account_attachment_created = accounting_api.create_account_attachment_by_file_name(
#                     xero_tenant_id,
#                     account_id,
#                     file_name=myimage.name,
#                     body=image.read(),
#                 )
#         except AccountingBadRequestException as exception:
#             output = "Error: " + exception.reason
#             json = jsonify(exception.error_data)

#     # GET ACCOUNT ATTACHMENTS
#     #[ACCOUNTS:GET_ATTACHMENTS]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_account_attachments = accounting_api.get_account_attachments(
#             xero_tenant_id, account_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Account attachments read {} total".format(
#             len(read_account_attachments.attachments)
#         )
#         json = serialize_model(read_account_attachments)
#     #[/ACCOUNTS:GET_ATTACHMENTS]

#     return render_template(
#         "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="get_attachments"
#     )

# @app.route("/accounting_account_get_attachment_by_file_name")
# @xero_token_required
# def accounting_account_get_attachment_by_file_name():
#     code = get_code_snippet("ACCOUNTS","GET_ATTACHMENTS")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     # CREATE ACCOUNT
#     account = Account(
#         name="FooBar" + get_random_num(),
#         code=get_random_num(),
#         description="My Foobar",
#         type=AccountType.EXPENSE,
#     )

#     try:
#         created_accounts = accounting_api.create_account(
#             xero_tenant_id, account
#         )
#         account_id = getvalue(created_accounts, "accounts.0.account_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         try:
#             include_online = True
#             myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
#             with myimage.open("rb") as image:
#                 account_attachment_created = accounting_api.create_account_attachment_by_file_name(
#                     xero_tenant_id,
#                     account_id,
#                     file_name=myimage.name,
#                     body=image.read(),
#                 )
#         except AccountingBadRequestException as exception:
#             output = "Error: " + exception.reason
#             json = jsonify(exception.error_data)

#     # GET ACCOUNT ATTACHMENTS
#     #[ACCOUNTS:GET_ATTACHMENTS]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_account_attachments = accounting_api.get_account_attachments(
#             xero_tenant_id, account_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Account attachments read {} total".format(
#             len(read_account_attachments.attachments)
#         )
#         json = serialize_model(read_account_attachments)
#     #[/ACCOUNTS:GET_ATTACHMENTS]

#     return render_template(
#         "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="get_attachments"
#     )

# @app.route("/accounting_bank_transaction_attachment_create_by_file_name")
# @xero_token_required
# def accounting_bank_transaction_attachment_create_by_file_name():
#     code = get_code_snippet("BANKTRANSACTIONATTACHMENTS","CREATEBYFILENAME")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONATTACHMENTS:CREATEBYFILENAME]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     file_name = "helo-heros.jpg"
#     path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
#     open_file = open(path_to_upload, 'rb')
#     body = open_file.read()

#     try:
#         created_bank_transaction_attachments_by_file_name = accounting_api.create_bank_transaction_attachment_by_file_name(
#             xero_tenant_id, bank_transaction_id, file_name, body
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank transaction attachment created with url {} .".format(
#             getvalue(created_bank_transaction_attachments_by_file_name, "attachments.0.url", "")
#         )
#         json = serialize_model(created_bank_transaction_attachments_by_file_name)
    
#     #[/BANKTRANSACTIONATTACHMENTS:CREATEBYFILENAME]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, output=output, json=json, len = 0, set="accounting", endpoint="bank_transaction", action="create_attachment_by_file_name"
#     )

# @app.route("/accounting_account_update_attachment")
# @xero_token_required
# def accounting_account_update_attachment():
#     code = get_code_snippet("ACCOUNTS","CREATE_ATTACHMENT")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     # CREATE ACCOUNT
#     account = Account(
#         name="FooBar" + get_random_num(),
#         code=get_random_num(),
#         description="My Foobar",
#         type=AccountType.EXPENSE,
#     )

#     try:
#         created_accounts = accounting_api.create_account(
#             xero_tenant_id, account
#         )
#         account_id = getvalue(created_accounts, "accounts.0.account_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     # CREATE ACCOUNT ATTACHMENT
#     #[ACCOUNTS:CREATE_ATTACHMENT]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         include_online = True
#         myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
#         with myimage.open("rb") as image:
#             account_attachment_created = accounting_api.create_account_attachment_by_file_name(
#                 xero_tenant_id,
#                 account_id,
#                 file_name=myimage.name,
#                 body=image.read(),
#             )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Attachment url '{}' created.".format(
#             getvalue(account_attachment_created, "attachments.0.url", "")
#         )
#         json = serialize_model(account_attachment_created)
#     #[/ACCOUNTS:CREATE_ATTACHMENT]

#     return render_template(
#         "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="create_attachment"
#     )

# RECEIPTS (DEPRECATED) TODO
# getReceipts x
# createReceipt x
# getReceipt x
# updateReceipt
# getReceiptAttachments
# getReceiptAttachmentById
# getReceiptAttachmentByFileName
# updateReceiptAttachmentByFileName
# createReceiptAttachmentByFileName
# getReceiptHistory
# createReceiptHistory
@app.route("/accounting_receipts_read_all")
@xero_token_required
def accounting_receipts_read_all():
    code = get_code_snippet("RECEIPTS","READ_ALL")

    #[RECEIPTS:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_receipts = accounting_api.get_receipts(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Receipts read {} total".format(
            len(read_receipts.receipts)
        )
        json = serialize_model(read_receipts)
    #[/RECEIPTS:READ_ALL]

    return render_template(
        "output.html", title="Receipts", code=code, json=json, output=output, len = 0, set="accounting", endpoint="receipts", action="read_all"
    )

@app.route("/accounting_receipts_read_one")
@xero_token_required
def accounting_receipts_read_one():
    code = get_code_snippet("RECEIPTS","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_receipts = accounting_api.get_receipts(
            xero_tenant_id
        )
        receipt_id = getvalue(read_receipts, "receipts.0.receipt_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[RECEIPTS:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_one_receipt = accounting_api.get_receipt(
            xero_tenant_id, receipt_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Receipt read with id {} ".format(
            getvalue(read_receipts, "receipts.0.receipt_id", "")
        )
        json = serialize_model(read_one_receipt)
    #[/RECEIPTS:READ_ONE]

    return render_template(
        "output.html", title="Receipts", code=code, json=json, output=output, len = 0, set="accounting", endpoint="receipts", action="read_one"
    )

@app.route("/accounting_receipts_create")
@xero_token_required
def accounting_receipts_create():
    code = get_code_snippet("RECEIPTS","CREATE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_contacts = accounting_api.get_contacts(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    try:
        read_users = accounting_api.get_users(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[RECEIPTS:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)
    unitdp = 4
    
    contact = Contact(
        contact_id = getvalue(read_contacts, "contacts.0.contact_id", ""))
    
    user = User(
        user_id = getvalue(read_users, "users.0.user_id", ""))
    
    line_item = LineItem(
        description = "Foobar",
        quantity = 1.0,
        unit_amount = 20.0,
        account_code = "300")
    
    line_items = []
    line_items.append(line_item)
    
    receipt = Receipt(
        contact = contact,
        user = user,
        line_items = line_items,
        line_amount_types = LineAmountTypes.INCLUSIVE,
        status = "DRAFT")
    
    receipts = Receipts(    
        receipts = [receipt])

    try:
        create_receipts = accounting_api.create_receipt(
            xero_tenant_id, receipts, unitdp
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Receipt created"
        json = serialize_model(create_receipts)
    #[/RECEIPTS:CREATE]

    return render_template(
        "output.html", title="Receipts", code=code, json=json, output=output, len = 0, set="accounting", endpoint="receipts", action="create"
    )

# @app.route("/accounting_account_get_attachments")
# @xero_token_required
# def accounting_account_get_attachments():
#     code = get_code_snippet("ACCOUNTS","GET_ATTACHMENTS")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     # CREATE ACCOUNT
#     account = Account(
#         name="FooBar" + get_random_num(),
#         code=get_random_num(),
#         description="My Foobar",
#         type=AccountType.EXPENSE,
#     )

#     try:
#         created_accounts = accounting_api.create_account(
#             xero_tenant_id, account
#         )
#         account_id = getvalue(created_accounts, "accounts.0.account_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         try:
#             include_online = True
#             myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
#             with myimage.open("rb") as image:
#                 account_attachment_created = accounting_api.create_account_attachment_by_file_name(
#                     xero_tenant_id,
#                     account_id,
#                     file_name=myimage.name,
#                     body=image.read(),
#                 )
#         except AccountingBadRequestException as exception:
#             output = "Error: " + exception.reason
#             json = jsonify(exception.error_data)

#     # GET ACCOUNT ATTACHMENTS
#     #[ACCOUNTS:GET_ATTACHMENTS]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_account_attachments = accounting_api.get_account_attachments(
#             xero_tenant_id, account_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Account attachments read {} total".format(
#             len(read_account_attachments.attachments)
#         )
#         json = serialize_model(read_account_attachments)
#     #[/ACCOUNTS:GET_ATTACHMENTS]

#     return render_template(
#         "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="get_attachments"
#     )

# @app.route("/accounting_account_get_attachment_by_id")
# @xero_token_required
# def accounting_account_get_attachment_by_id():
#     code = get_code_snippet("ACCOUNTS","GET_ATTACHMENTS")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     # CREATE ACCOUNT
#     account = Account(
#         name="FooBar" + get_random_num(),
#         code=get_random_num(),
#         description="My Foobar",
#         type=AccountType.EXPENSE,
#     )

#     try:
#         created_accounts = accounting_api.create_account(
#             xero_tenant_id, account
#         )
#         account_id = getvalue(created_accounts, "accounts.0.account_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         try:
#             include_online = True
#             myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
#             with myimage.open("rb") as image:
#                 account_attachment_created = accounting_api.create_account_attachment_by_file_name(
#                     xero_tenant_id,
#                     account_id,
#                     file_name=myimage.name,
#                     body=image.read(),
#                 )
#         except AccountingBadRequestException as exception:
#             output = "Error: " + exception.reason
#             json = jsonify(exception.error_data)

#     # GET ACCOUNT ATTACHMENTS
#     #[ACCOUNTS:GET_ATTACHMENTS]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_account_attachments = accounting_api.get_account_attachments(
#             xero_tenant_id, account_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Account attachments read {} total".format(
#             len(read_account_attachments.attachments)
#         )
#         json = serialize_model(read_account_attachments)
#     #[/ACCOUNTS:GET_ATTACHMENTS]

#     return render_template(
#         "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="get_attachments"
#     )

# @app.route("/accounting_account_get_attachment_by_file_name")
# @xero_token_required
# def accounting_account_get_attachment_by_file_name():
#     code = get_code_snippet("ACCOUNTS","GET_ATTACHMENTS")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     # CREATE ACCOUNT
#     account = Account(
#         name="FooBar" + get_random_num(),
#         code=get_random_num(),
#         description="My Foobar",
#         type=AccountType.EXPENSE,
#     )

#     try:
#         created_accounts = accounting_api.create_account(
#             xero_tenant_id, account
#         )
#         account_id = getvalue(created_accounts, "accounts.0.account_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         try:
#             include_online = True
#             myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
#             with myimage.open("rb") as image:
#                 account_attachment_created = accounting_api.create_account_attachment_by_file_name(
#                     xero_tenant_id,
#                     account_id,
#                     file_name=myimage.name,
#                     body=image.read(),
#                 )
#         except AccountingBadRequestException as exception:
#             output = "Error: " + exception.reason
#             json = jsonify(exception.error_data)

#     # GET ACCOUNT ATTACHMENTS
#     #[ACCOUNTS:GET_ATTACHMENTS]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_account_attachments = accounting_api.get_account_attachments(
#             xero_tenant_id, account_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Account attachments read {} total".format(
#             len(read_account_attachments.attachments)
#         )
#         json = serialize_model(read_account_attachments)
#     #[/ACCOUNTS:GET_ATTACHMENTS]

#     return render_template(
#         "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="get_attachments"
#     )

# @app.route("/accounting_bank_transaction_attachment_create_by_file_name")
# @xero_token_required
# def accounting_bank_transaction_attachment_create_by_file_name():
#     code = get_code_snippet("BANKTRANSACTIONATTACHMENTS","CREATEBYFILENAME")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONATTACHMENTS:CREATEBYFILENAME]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     file_name = "helo-heros.jpg"
#     path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
#     open_file = open(path_to_upload, 'rb')
#     body = open_file.read()

#     try:
#         created_bank_transaction_attachments_by_file_name = accounting_api.create_bank_transaction_attachment_by_file_name(
#             xero_tenant_id, bank_transaction_id, file_name, body
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank transaction attachment created with url {} .".format(
#             getvalue(created_bank_transaction_attachments_by_file_name, "attachments.0.url", "")
#         )
#         json = serialize_model(created_bank_transaction_attachments_by_file_name)
    
#     #[/BANKTRANSACTIONATTACHMENTS:CREATEBYFILENAME]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, output=output, json=json, len = 0, set="accounting", endpoint="bank_transaction", action="create_attachment_by_file_name"
#     )

# @app.route("/accounting_account_update_attachment")
# @xero_token_required
# def accounting_account_update_attachment():
#     code = get_code_snippet("ACCOUNTS","CREATE_ATTACHMENT")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     # CREATE ACCOUNT
#     account = Account(
#         name="FooBar" + get_random_num(),
#         code=get_random_num(),
#         description="My Foobar",
#         type=AccountType.EXPENSE,
#     )

#     try:
#         created_accounts = accounting_api.create_account(
#             xero_tenant_id, account
#         )
#         account_id = getvalue(created_accounts, "accounts.0.account_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     # CREATE ACCOUNT ATTACHMENT
#     #[ACCOUNTS:CREATE_ATTACHMENT]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         include_online = True
#         myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
#         with myimage.open("rb") as image:
#             account_attachment_created = accounting_api.create_account_attachment_by_file_name(
#                 xero_tenant_id,
#                 account_id,
#                 file_name=myimage.name,
#                 body=image.read(),
#             )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Attachment url '{}' created.".format(
#             getvalue(account_attachment_created, "attachments.0.url", "")
#         )
#         json = serialize_model(account_attachment_created)
#     #[/ACCOUNTS:CREATE_ATTACHMENT]

#     return render_template(
#         "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="create_attachment"
#     )

# @app.route("/accounting_bank_transaction_history_read")
# @xero_token_required
# def accounting_bank_transaction_history_read():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","READ")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:READ]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transaction_history = accounting_api.get_bank_transactions_history(
#             xero_tenant_id, bank_transaction_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank Transaction History read {} total".format(
#             len(read_bank_transaction_history.history_records)
#         )
#         json = serialize_model(read_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:READ]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="read_history"
#     )

# @app.route("/accounting_bank_transaction_history_create")
# @xero_token_required
# def accounting_bank_transaction_history_create():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","CREATE")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:CREATE]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     history_record = HistoryRecord(
#         details = "I'm a history record " + get_random_num()
#     )

#     history_records = HistoryRecords(
#         history_records = [history_record]
#     )

#     try:
#         create_bank_transaction_history = accounting_api.create_bank_transaction_history_record(
#             xero_tenant_id, bank_transaction_id, history_records
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank transaction history added with details {} .".format(
#             getvalue(create_bank_transaction_history, "history_records.0.details", "")
#         )
#         json = serialize_model(create_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:CREATE]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="create_history"
#     )

# REPEATING INVOICES TODO
# getRepeatingInvoices x
# getRepeatingInvoice x
# getRepeatingInvoiceAttachments
# getRepeatingInvoiceAttachmentById
# getRepeatingInvoiceAttachmentByFileName
# updateRepeatingInvoiceAttachmentByFileName
# createRepeatingInvoiceAttachmentByFileName
# getRepeatingInvoiceHistory x
# createRepeatingInvoiceHistory
@app.route("/accounting_repeating_invoices_read_all")
@xero_token_required
def accounting_repeating_invoices_read_all():
    code = get_code_snippet("REPEATING_INVOICES","READ_ALL")

    #[REPEATING_INVOICES:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_repeating_invoices = accounting_api.get_repeating_invoices(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Repeating Invoices read {} total".format(
            len(read_repeating_invoices.repeating_invoices)
        )
        json = serialize_model(read_repeating_invoices)
    #[/REPEATING_INVOICES:READ_ALL]

    return render_template(
        "output.html", title="Repeating Invoices", code=code, json=json, output=output, len = 0, set="accounting", endpoint="repeating_invoices", action="read_all"
    )

@app.route("/accounting_repeating_invoices_read_one")
@xero_token_required
def accounting_repeating_invoices_read_one():
    code = get_code_snippet("REPEATING_INVOICES","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_repeating_invoices = accounting_api.get_repeating_invoices(
            xero_tenant_id
        )
        repeating_invoice_id = getvalue(read_repeating_invoices, "repeating_invoices.0.repeating_invoice_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[REPEATING_INVOICES:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_one_repeating_invoice = accounting_api.get_repeating_invoice(
            xero_tenant_id, repeating_invoice_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Repeating Invoice read with id {} ".format(
            getvalue(read_repeating_invoices, "repeating_invoices.0.repeating_invoice_id", "")
        )
        json = serialize_model(read_one_repeating_invoice)
    #[/REPEATING_INVOICES:READ_ONE]

    return render_template(
        "output.html", title="Repeating Invoices", code=code, json=json, output=output, len = 0, set="accounting", endpoint="repeating_invoices", action="read_one"
    )

@app.route("/accounting_repeating_invoices_create")
@xero_token_required
def accounting_repeating_invoices_create():
    code = get_code_snippet("REPEATING_INVOICES","CREATE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    # READ CONTACT
    try:
        read_contacts = accounting_api.get_contacts(
            xero_tenant_id
        )
        contact_id = getvalue(read_contacts, "contacts.0.contact_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    # READ ACCOUNT
    where = "Type==\"SALES\"&&Status==\"ACTIVE\""
    try:
        read_accounts = accounting_api.get_accounts(
            xero_tenant_id, where=where
        )
        account_id = getvalue(read_accounts, "accounts.0.account_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[REPEATING_INVOICES:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    contact = Contact(
        contact_id=contact_id
    )

    line_item = LineItem(
        account_id=account_id,
        description= "Consulting",
        quantity=1.0,
        unit_amount=10.0,
    )

    schedule = Schedule(
        period=1,
        unit="MONTHLY",
        due_date=31,
        due_date_type= "OFCURRENTMONTH",
        start_date=dateutil.parser.parse("2022-08-30T00:00:00"),
        next_scheduled_date=dateutil.parser.parse("2022-09-06T00:00:00")
    )

    repeating_invoice = RepeatingInvoice(
        line_items=[line_item],
        contact=contact,
        schedule=schedule,
        type="ACCREC",
        approved_for_sending=False,
        status="DRAFT"
    )

    repeating_invoices = RepeatingInvoices(repeating_invoices=[repeating_invoice])

    try:
        created_repeating_invoices = accounting_api.create_repeating_invoices(
            xero_tenant_id, repeating_invoices=repeating_invoices
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "New repeating invoice created with ID '{}'.".format(
            getvalue(created_repeating_invoices, "repeating_invoices.0.repeating_invoice_id", "")
        )
        json = serialize_model(created_repeating_invoices)
    #[/REPEATING_INVOICES:CREATE]

    return render_template(
        "output.html", title="Repeating Invoices", code=code, output=output, json=json, len = 0, set="accounting", endpoint="repeating_invoices", action="create"
    )

@app.route("/accounting_repeating_invoices_read_history")
@xero_token_required
def accounting_repeating_invoices_read_history():
    code = get_code_snippet("REPEATING_INVOICES","READ_HISTORY")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_repeating_invoices = accounting_api.get_repeating_invoices(
            xero_tenant_id
        )
        repeating_invoice_id = getvalue(read_repeating_invoices, "repeating_invoices.0.repeating_invoice_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[REPEATING_INVOICES:READ_HISTORY]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_repeating_invoice_history = accounting_api.get_repeating_invoice_history(
            xero_tenant_id, repeating_invoice_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Repeating Invoice History Read"
        json = serialize_model(read_repeating_invoice_history)
    #[/REPEATING_INVOICES:READ_HISTORY]

    return render_template(
        "output.html", title="Repeating Invoice History Read", code=code, json=json, output=output, len = 0, set="accounting", endpoint="repeating_invoices", action="read_history"
    )

@app.route("/accounting_repeating_invoices_create_history")
@xero_token_required
def accounting_repeating_invoices_create_history():
    code = get_code_snippet("REPEATING_INVOICES","CREATE_HISTORY")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_repeating_invoices = accounting_api.get_repeating_invoices(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[REPEATING_INVOICES:CREATE_HISTORY]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)
    repeating_invoice_id = getvalue(read_repeating_invoices, "repeating_invoices.0.repeating_invoice_id", "")

    history_record = HistoryRecord(
        details = "Hello World")

    history_records = HistoryRecords( 
        history_records = [history_record])

    try:
        created_repeating_invoice_history = accounting_api.create_repeating_invoice_history(
            xero_tenant_id, repeating_invoice_id=repeating_invoice_id, history_records=history_records
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Repeating Invoice History Created"
        json = serialize_model(created_repeating_invoice_history)
    #[/REPEATING_INVOICES:CREATE_HISTORY]

    return render_template(
        "output.html", title="Repeating Invoice History Created", code=code, json=json, output=output, len = 0, set="accounting", endpoint="repeating_invoices", action="create_history"
    )

# @app.route("/accounting_account_get_attachments")
# @xero_token_required
# def accounting_account_get_attachments():
#     code = get_code_snippet("ACCOUNTS","GET_ATTACHMENTS")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     # CREATE ACCOUNT
#     account = Account(
#         name="FooBar" + get_random_num(),
#         code=get_random_num(),
#         description="My Foobar",
#         type=AccountType.EXPENSE,
#     )

#     try:
#         created_accounts = accounting_api.create_account(
#             xero_tenant_id, account
#         )
#         account_id = getvalue(created_accounts, "accounts.0.account_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         try:
#             include_online = True
#             myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
#             with myimage.open("rb") as image:
#                 account_attachment_created = accounting_api.create_account_attachment_by_file_name(
#                     xero_tenant_id,
#                     account_id,
#                     file_name=myimage.name,
#                     body=image.read(),
#                 )
#         except AccountingBadRequestException as exception:
#             output = "Error: " + exception.reason
#             json = jsonify(exception.error_data)

#     # GET ACCOUNT ATTACHMENTS
#     #[ACCOUNTS:GET_ATTACHMENTS]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_account_attachments = accounting_api.get_account_attachments(
#             xero_tenant_id, account_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Account attachments read {} total".format(
#             len(read_account_attachments.attachments)
#         )
#         json = serialize_model(read_account_attachments)
#     #[/ACCOUNTS:GET_ATTACHMENTS]

#     return render_template(
#         "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="get_attachments"
#     )

# @app.route("/accounting_account_get_attachment_by_id")
# @xero_token_required
# def accounting_account_get_attachment_by_id():
#     code = get_code_snippet("ACCOUNTS","GET_ATTACHMENTS")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     # CREATE ACCOUNT
#     account = Account(
#         name="FooBar" + get_random_num(),
#         code=get_random_num(),
#         description="My Foobar",
#         type=AccountType.EXPENSE,
#     )

#     try:
#         created_accounts = accounting_api.create_account(
#             xero_tenant_id, account
#         )
#         account_id = getvalue(created_accounts, "accounts.0.account_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         try:
#             include_online = True
#             myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
#             with myimage.open("rb") as image:
#                 account_attachment_created = accounting_api.create_account_attachment_by_file_name(
#                     xero_tenant_id,
#                     account_id,
#                     file_name=myimage.name,
#                     body=image.read(),
#                 )
#         except AccountingBadRequestException as exception:
#             output = "Error: " + exception.reason
#             json = jsonify(exception.error_data)

#     # GET ACCOUNT ATTACHMENTS
#     #[ACCOUNTS:GET_ATTACHMENTS]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_account_attachments = accounting_api.get_account_attachments(
#             xero_tenant_id, account_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Account attachments read {} total".format(
#             len(read_account_attachments.attachments)
#         )
#         json = serialize_model(read_account_attachments)
#     #[/ACCOUNTS:GET_ATTACHMENTS]

#     return render_template(
#         "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="get_attachments"
#     )

# @app.route("/accounting_account_get_attachment_by_file_name")
# @xero_token_required
# def accounting_account_get_attachment_by_file_name():
#     code = get_code_snippet("ACCOUNTS","GET_ATTACHMENTS")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     # CREATE ACCOUNT
#     account = Account(
#         name="FooBar" + get_random_num(),
#         code=get_random_num(),
#         description="My Foobar",
#         type=AccountType.EXPENSE,
#     )

#     try:
#         created_accounts = accounting_api.create_account(
#             xero_tenant_id, account
#         )
#         account_id = getvalue(created_accounts, "accounts.0.account_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         try:
#             include_online = True
#             myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
#             with myimage.open("rb") as image:
#                 account_attachment_created = accounting_api.create_account_attachment_by_file_name(
#                     xero_tenant_id,
#                     account_id,
#                     file_name=myimage.name,
#                     body=image.read(),
#                 )
#         except AccountingBadRequestException as exception:
#             output = "Error: " + exception.reason
#             json = jsonify(exception.error_data)

#     # GET ACCOUNT ATTACHMENTS
#     #[ACCOUNTS:GET_ATTACHMENTS]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_account_attachments = accounting_api.get_account_attachments(
#             xero_tenant_id, account_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Account attachments read {} total".format(
#             len(read_account_attachments.attachments)
#         )
#         json = serialize_model(read_account_attachments)
#     #[/ACCOUNTS:GET_ATTACHMENTS]

#     return render_template(
#         "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="get_attachments"
#     )

# @app.route("/accounting_bank_transaction_attachment_create_by_file_name")
# @xero_token_required
# def accounting_bank_transaction_attachment_create_by_file_name():
#     code = get_code_snippet("BANKTRANSACTIONATTACHMENTS","CREATEBYFILENAME")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONATTACHMENTS:CREATEBYFILENAME]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     file_name = "helo-heros.jpg"
#     path_to_upload = Path(__file__).resolve().parent.joinpath(file_name)
#     open_file = open(path_to_upload, 'rb')
#     body = open_file.read()

#     try:
#         created_bank_transaction_attachments_by_file_name = accounting_api.create_bank_transaction_attachment_by_file_name(
#             xero_tenant_id, bank_transaction_id, file_name, body
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank transaction attachment created with url {} .".format(
#             getvalue(created_bank_transaction_attachments_by_file_name, "attachments.0.url", "")
#         )
#         json = serialize_model(created_bank_transaction_attachments_by_file_name)
    
#     #[/BANKTRANSACTIONATTACHMENTS:CREATEBYFILENAME]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, output=output, json=json, len = 0, set="accounting", endpoint="bank_transaction", action="create_attachment_by_file_name"
#     )

# @app.route("/accounting_account_update_attachment")
# @xero_token_required
# def accounting_account_update_attachment():
#     code = get_code_snippet("ACCOUNTS","CREATE_ATTACHMENT")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     # CREATE ACCOUNT
#     account = Account(
#         name="FooBar" + get_random_num(),
#         code=get_random_num(),
#         description="My Foobar",
#         type=AccountType.EXPENSE,
#     )

#     try:
#         created_accounts = accounting_api.create_account(
#             xero_tenant_id, account
#         )
#         account_id = getvalue(created_accounts, "accounts.0.account_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     # CREATE ACCOUNT ATTACHMENT
#     #[ACCOUNTS:CREATE_ATTACHMENT]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         include_online = True
#         myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
#         with myimage.open("rb") as image:
#             account_attachment_created = accounting_api.create_account_attachment_by_file_name(
#                 xero_tenant_id,
#                 account_id,
#                 file_name=myimage.name,
#                 body=image.read(),
#             )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Attachment url '{}' created.".format(
#             getvalue(account_attachment_created, "attachments.0.url", "")
#         )
#         json = serialize_model(account_attachment_created)
#     #[/ACCOUNTS:CREATE_ATTACHMENT]

#     return render_template(
#         "output.html", title="Accounts", code=code, output=output, json=json, len = 0, set="accounting", endpoint="account", action="create_attachment"
#     )

# @app.route("/accounting_bank_transaction_history_read")
# @xero_token_required
# def accounting_bank_transaction_history_read():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","READ")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:READ]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transaction_history = accounting_api.get_bank_transactions_history(
#             xero_tenant_id, bank_transaction_id
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank Transaction History read {} total".format(
#             len(read_bank_transaction_history.history_records)
#         )
#         json = serialize_model(read_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:READ]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="read_history"
#     )

# @app.route("/accounting_bank_transaction_history_create")
# @xero_token_required
# def accounting_bank_transaction_history_create():
#     code = get_code_snippet("BANKTRANSACTIONHISTORY","CREATE")
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     try:
#         read_bank_transactions = accounting_api.get_bank_transactions(
#             xero_tenant_id
#         )
#         bank_transaction_id = getvalue(read_bank_transactions, "bank_transactions.0.bank_transaction_id", "")
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)

#     #[BANKTRANSACTIONHISTORY:CREATE]
#     xero_tenant_id = get_xero_tenant_id()
#     accounting_api = AccountingApi(api_client)

#     history_record = HistoryRecord(
#         details = "I'm a history record " + get_random_num()
#     )

#     history_records = HistoryRecords(
#         history_records = [history_record]
#     )

#     try:
#         create_bank_transaction_history = accounting_api.create_bank_transaction_history_record(
#             xero_tenant_id, bank_transaction_id, history_records
#         )
#     except AccountingBadRequestException as exception:
#         output = "Error: " + exception.reason
#         json = jsonify(exception.error_data)
#     else:
#         output = "Bank transaction history added with details {} .".format(
#             getvalue(create_bank_transaction_history, "history_records.0.details", "")
#         )
#         json = serialize_model(create_bank_transaction_history)
#     #[/BANKTRANSACTIONHISTORY:CREATE]

#     return render_template(
#         "output.html", title="Bank Transactions", code=code, json=json, output=output, len = 0, set="accounting", endpoint="bank_transaction", action="create_history"
#     )

# REPORTS TODO
# getReportTenNinetyNine x
# getReportAgedPayablesByContact x
# getReportAgedReceivablesByContact x
# getReportBalanceSheet x
# getReportBankSummary x
# getReportBASorGSTList x
# getReportBASorGST x  
# getReportBudgetSummary x
# getReportExecutiveSummary x
# getReportProfitAndLoss x
# getReportTrialBalance x
@app.route("/accounting_reports_read_ten_ninety_nine")
@xero_token_required
def accounting_reports_read_ten_ninety_nine():
    code = get_code_snippet("REPORTS_TEN_NINETY_NINE","READ")

    #This report is sepcific to US Xero Organisations

    #[REPORTS_TEN_NINETY_NINE:READ]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)
    report_year = '2020'

    try:
        read_report_ten_ninety_nine = accounting_api.get_report_ten_ninety_nine(
            xero_tenant_id, report_year
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "1099 Report Read"
        json = serialize_model(read_report_ten_ninety_nine)
    #[/REPORTS_TEN_NINETY_NINE:READ]

    return render_template(
        "output.html", title="Reports - 1099", code=code, json=json, output=output, len = 0, set="accounting", endpoint="reports", action="read_ten_ninety_nine"
    )

@app.route("/accounting_reports_read_aged_payables_by_contact")
@xero_token_required
def accounting_reports_read_aged_payables_by_contact():
    code = get_code_snippet("REPORTS_AGED_PAYABLES_BY_CONTACT","READ")

    #This report is sepcific to AU (BAS) and NZ (GST) Xero Organisations

    #[REPORTS_AGED_PAYABLES_BY_CONTACT:READ]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    read_contacts = accounting_api.get_contacts(
            xero_tenant_id
        )

    contact_id = getvalue(read_contacts, "contacts.0.contact_id", "")
    date = dateutil.parser.parse("2021-04-30")

    try:
        read_report_aged_payables_by_contact = accounting_api.get_report_aged_payables_by_contact(
            xero_tenant_id, contact_id, date
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Aged Payables by Contact"
        json = serialize_model(read_report_aged_payables_by_contact)
    #[/REPORTS_AGED_PAYABLES_BY_CONTACT:READ]

    return render_template(
        "output.html", title="Reports - Aged Payables by Contact", code=code, json=json, output=output, len = 0, set="accounting", endpoint="reports", action="read_aged_payables_by_contact"
    )

@app.route("/accounting_reports_read_aged_receivables_by_contact")
@xero_token_required
def accounting_reports_read_aged_receivables_by_contact():
    code = get_code_snippet("REPORTS_AGED_RECEIVABLES_BY_CONTACT","READ")

    #This report is sepcific to AU (BAS) and NZ (GST) Xero Organisations

    #[REPORTS_AGED_RECEIVABLES_BY_CONTACT:READ]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    read_contacts = accounting_api.get_contacts(
            xero_tenant_id
        )

    contact_id = getvalue(read_contacts, "contacts.0.contact_id", "")
    date = dateutil.parser.parse("2021-04-30")

    try:
        read_report_aged_receivables_by_contact = accounting_api.get_report_aged_receivables_by_contact(
            xero_tenant_id, contact_id, date
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Aged Receivables by Contact"
        json = serialize_model(read_report_aged_receivables_by_contact)
    #[/REPORTS_AGED_RECEIVABLES_BY_CONTACT:READ]

    return render_template(
        "output.html", title="Reports - Aged Receivables by Contact", code=code, json=json, output=output, len = 0, set="accounting", endpoint="reports", action="read_aged_receivables_by_contact"
    )

@app.route("/accounting_reports_read_balance_sheet")
@xero_token_required
def accounting_reports_read_balance_sheet():
    code = get_code_snippet("REPORTS_BALANCE_SHEET","READ")

    #[REPORTS_BALANCE_SHEET:READ]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)
    date = dateutil.parser.parse("2021-01-01")
    periods = 3
    timeframe = 'MONTH'
    standard_layout = 'true'
    payments_only = 'false'

    try:
        read_report_balance_sheet = accounting_api.get_report_balance_sheet(
            xero_tenant_id, date, periods, timeframe, standard_layout, payments_only
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Balance Sheet Report Read"
        json = serialize_model(read_report_balance_sheet)
    #[/REPORTS_BALANCE_SHEET:READ]

    return render_template(
        "output.html", title="Reports - Balance Sheet", code=code, json=json, output=output, len = 0, set="accounting", endpoint="reports", action="read_balance_sheet"
    )

@app.route("/accounting_reports_read_bank_summary")
@xero_token_required
def accounting_reports_read_bank_summary():
    code = get_code_snippet("REPORTS_BANK_SUMMARY","READ")

    #[REPORTS_BANK_SUMMARY:READ]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)
    from_date = dateutil.parser.parse("2021-01-01")
    to_date = dateutil.parser.parse("2021-01-31")

    try:
        read_report_bank_summary = accounting_api.get_report_bank_summary(
            xero_tenant_id, from_date, to_date
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Bank Summary Report Read"
        json = serialize_model(read_report_bank_summary)
    #[/REPORTS_BANK_SUMMARY:READ]

    return render_template(
        "output.html", title="Reports - Bank Summary", code=code, json=json, output=output, len = 0, set="accounting", endpoint="reports", action="read_bank_summary"
    )

@app.route("/accounting_report_get_reports_list")
@xero_token_required
def accounting_report_get_reports_list():
    code = get_code_snippet("GET_REPORTS_LIST","READ")

    #This report is sepcific to AU (BAS) and NZ (GST) Xero Organisations

    #[GET_REPORTS_LIST:READ]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        get_reports_list = accounting_api.get_reports_list(
            xero_tenant_id,
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "List Report Read"
        json = serialize_model(get_reports_list)
    #[/GET_REPORTS_LIST:READ]

    return render_template(
        "output.html", title="Reports - List", code=code, json=json, output=output, len = 0, set="accounting", endpoint="reports", action="get_reports_list"
    )

@app.route("/accounting_report_get_report_from_id")
@xero_token_required
def accounting_report_get_report_from_id():
    code = get_code_snippet("REPORT_FROM_ID","READ")

    #This report is sepcific to AU (BAS) and NZ (GST) Xero Organisations

    #[REPORT_FROM_ID:READ]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    get_reports_list = accounting_api.get_reports_list(
        xero_tenant_id,
    )

    report_id = getvalue(get_reports_list, "reports.0.report_id", "")

    try:
        read_report = accounting_api.get_report_from_id(
            xero_tenant_id, report_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Report Read"
        json = serialize_model(read_report)
    #[/REPORT_FROM_ID:READ]

    return render_template(
        "output.html", title="Reports - Report", code=code, json=json, output=output, len = 0, set="accounting", endpoint="reports", action="get_report_from_id"
    )

@app.route("/accounting_reports_read_budget_summary")
@xero_token_required
def accounting_reports_read_budget_summary():
    code = get_code_snippet("REPORTS_BUDGET_SUMMARY","READ")

    #[REPORTS_BUDGET_SUMMARY:READ]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)
    period = 1
    #date = date.today()

    try:
        read_report_budget_summary = accounting_api.get_report_budget_summary(
            xero_tenant_id, period
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Budget Summary Report Read"
        json = serialize_model(read_report_budget_summary)
    #[/REPORTS_BUDGET_SUMMARY:READ]

    return render_template(
        "output.html", title="Reports - Budget Summary", code=code, json=json, output=output, len = 0, set="accounting", endpoint="reports", action="read_budget_summary"
    )

@app.route("/accounting_reports_read_executive_summary")
@xero_token_required
def accounting_reports_read_executive_summary():
    code = get_code_snippet("REPORTS_EXECUTIVE_SUMMARY","READ")

    #[REPORTS_EXECUTIVE_SUMMARY:READ]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)
    date = dateutil.parser.parse("2021-01-01")

    try:
        read_report_executive_summary = accounting_api.get_report_executive_summary(
            xero_tenant_id, date
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Executive Summary Report Read"
        json = serialize_model(read_report_executive_summary)
    #[/REPORTS_EXECUTIVE_SUMMARY:READ]

    return render_template(
        "output.html", title="Reports - Executive Summary", code=code, json=json, output=output, len = 0, set="accounting", endpoint="reports", action="read_executive_summary"
    )

@app.route("/accounting_reports_read_profit_and_loss")
@xero_token_required
def accounting_reports_read_profit_and_loss():
    code = get_code_snippet("REPORTS_PROFIT_AND_LOSS","READ")

    #[REPORTS_PROFIT_AND_LOSS:READ]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)
    from_date = dateutil.parser.parse("2021-01-31")
    to_date = dateutil.parser.parse("2021-01-31")
    periods = 1
    timeframe = 'MONTH'
    standard_layout = 'true'
    payments_only = 'false'

    try:
        read_report_profit_and_loss = accounting_api.get_report_profit_and_loss(
            xero_tenant_id, from_date=from_date, to_date=to_date, periods=periods, timeframe=timeframe, standard_layout=standard_layout, payments_only=payments_only
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Profit & Loss Report Read"
        json = serialize_model(read_report_profit_and_loss)
    #[/REPORTS_PROFIT_AND_LOSS:READ]

    return render_template(
        "output.html", title="Reports - Profit & Loss", code=code, json=json, output=output, len = 0, set="accounting", endpoint="reports", action="read_profit_and_loss"
    )

@app.route("/accounting_reports_read_trial_balance")
@xero_token_required
def accounting_reports_read_trial_balance():
    code = get_code_snippet("REPORTS_TRIAL_BALANCE","READ")

    #[REPORTS_TRIAL_BALANCE:READ]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)
    date = dateutil.parser.parse("2021-01-01")
    payments_only = 'true'

    try:
        read_report_trial_balance = accounting_api.get_report_trial_balance(
            xero_tenant_id, date, payments_only
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Trial Balance Report Read"
        json = serialize_model(read_report_trial_balance)
    #[/REPORTS_TRIAL_BALANCE:READ]

    return render_template(
        "output.html", title="Reports - Trial Balance", code=code, json=json, output=output, len = 0, set="accounting", endpoint="reports", action="read_trial_balance"
    )

# TAX RATES TODO
# getTaxRates x
# createTaxRates x
# updateTaxRate x
@app.route("/accounting_tax_rate_read_all")
@xero_token_required
def accounting_tax_rate_read_all():
    code = get_code_snippet("TAX_RATES","READ_ALL")

    #[TAX_RATES:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_tax_rates = accounting_api.get_tax_rates(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Tax rates read {} total".format(
            len(read_tax_rates.tax_rates)
        )
        json = serialize_model(read_tax_rates)
    #[/TAX_RATES:READ_ALL]

    return render_template(
        "output.html", title="Tax Rates", code=code, json=json, output=output, len = 0, set="accounting", endpoint="tax_rate", action="read_all"
    )

@app.route("/accounting_tax_rate_create")
@xero_token_required
def accounting_tax_rate_create():
    code = get_code_snippet("TAX_RATES","CREATE")

    #[TAX_RATES:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    tax_component = TaxComponent(
        name = "Example Tax",
        rate = 20.00)

    #report_tax_type is invalid for US orgs.
    
    tax_rate = TaxRate(
        name = "Example Tax Rate",  
        report_tax_type = "INPUT", 
        tax_components = [tax_component])
    
    tax_rates = TaxRates(    
        tax_rates = [tax_rate])

    try:
        create_tax_rates = accounting_api.create_tax_rates(
            xero_tenant_id, tax_rates
        )

    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Tax Rate created with name {}.".format(
            getvalue(create_tax_rates, "tax_rates.0.name", "")
        )
        json = serialize_model(create_tax_rates)
    #[/TAX_RATES:CREATE]

    return render_template(
        "output.html", title="Tax Rates", code=code, json=json, output=output, len = 0, set="accounting", endpoint="tax_rate", action="create"
    )

@app.route("/accounting_tax_rate_update")
@xero_token_required
def accounting_tax_rate_update():
    code = get_code_snippet("TAX_RATES","UPDATE")

    #[TAX_RATES:UPDATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    read_tax_rates = accounting_api.get_tax_rates(
            xero_tenant_id
        )

    updated_tax_component = TaxComponent(
        name = "Example Tax " + get_random_num(),
        rate = 20.00)

    #report_tax_type is invalid for US orgs.
    
    tax_rate = TaxRate(
        name = getvalue(read_tax_rates, "tax_rates.0.name", ""), 
        tax_components = [updated_tax_component])

    
    tax_rates = TaxRates(    
        tax_rates = [tax_rate])

    try:
        update_tax_rates = accounting_api.update_tax_rate(
            xero_tenant_id, tax_rates
        )

    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Tax Rate updated with name {}.".format(
            getvalue(update_tax_rates, "tax_rates.0.name", "")
        )
        json = serialize_model(update_tax_rates)
    #[/TAX_RATES:UPDATE]

    return render_template(
        "output.html", title="Tax Rates", code=code, json=json, output=output, len = 0, set="accounting", endpoint="tax_rate", action="update"
    )

# TRACKING CATEGORIES TODO
# getTrackingCategories x
# createTrackingCategory x
# getTrackingCategory x
# updateTrackingCategory x
# deleteTrackingCategory x
# createTrackingOptions x
# updateTrackingOptions x
# deleteTrackingOptions x
@app.route("/accounting_tracking_categories_read_all")
@xero_token_required
def accounting_tracking_categories_read_all():
    code = get_code_snippet("TRACKING_CATEGORIES","READ_ALL")

    #[TRACKING_CATEGORIES:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_tracking_categories = accounting_api.get_tracking_categories(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Tracking Categories read {} total".format(
            len(read_tracking_categories.tracking_categories)
        )
        json = serialize_model(read_tracking_categories)
    #[/TRACKING_CATEGORIES:READ_ALL]

    return render_template(
        "output.html", title="Tracking Categories", code=code, json=json, output=output, len = 0, set="accounting", endpoint="tracking_categories", action="read_all"
    )

@app.route("/accounting_tracking_categories_read_one")
@xero_token_required
def accounting_tracking_categories_read_one():
    code = get_code_snippet("TRACKING_CATEGORIES","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_tracking_categories = accounting_api.get_tracking_categories(
            xero_tenant_id
        )
        tracking_category_id = getvalue(read_tracking_categories, "tracking_categories.0.tracking_category_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[TRACKING_CATEGORIES:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_one_tracking_category = accounting_api.get_tracking_category(
            xero_tenant_id, tracking_category_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Tracking Category read with id {} ".format(
            getvalue(read_tracking_categories, "tracking_categories.0.tracking_category_id", "")
        )
        json = serialize_model(read_one_tracking_category)
    #[/TRACKING_CATEGORIES:READ_ONE]

    return render_template(
        "output.html", title="Tracking Category", code=code, json=json, output=output, len = 0, set="accounting", endpoint="tracking_categories", action="read_one"
    )

@app.route("/accounting_tracking_categories_create")
@xero_token_required
def accounting_tracking_categories_create():
    code = get_code_snippet("TRACKING_CATEGORIES","CREATE")

    #[TRACKING_CATEGORIES:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    tracking_category = TrackingCategory(
        name = "Foobar" + get_random_num())

    try:
        created_tracking_category = accounting_api.create_tracking_category(
            xero_tenant_id, tracking_category
        )
        account_id = getvalue(created_tracking_category, "tracking_categories.0.tracking_category_id", "")

    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Tracking Category created with ID {} .".format(
            getvalue(created_tracking_category, "tracking_categories.0.tracking_category_id", "")
        )
        json = serialize_model(created_tracking_category)
    #[/TRACKING_CATEGORIES:CREATE]

    return render_template(
        "output.html", title="Tracking Categories", code=code, output=output, json=json, len = 0, set="accounting", endpoint="tracking_categories", action="create"
    )

@app.route("/accounting_tracking_categories_update")
@xero_token_required
def accounting_tracking_categories_update():
    code = get_code_snippet("TRACKING_CATEGORIES","UPDATE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    tracking_category = accounting_api.get_tracking_categories(
            xero_tenant_id
        )
    tracking_category_id = getvalue(tracking_category, "tracking_categories.0.tracking_category_id", "")

    tracking_category = TrackingCategory(
        name = "Foobar" + get_random_num())

    #[TRACKING_CATEGORIES:UPDATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        updated_tracking_category = accounting_api.update_tracking_category(
            xero_tenant_id, tracking_category_id, tracking_category
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Tracking Category updated."
        json = serialize_model(updated_tracking_category)
    #[/TRACKING_CATEGORIES:UPDATE]

    return render_template(
        "output.html", title="Tracking Categories", code=code, output=output, json=json, len = 0, set="accounting", endpoint="tracking_categories", action="update"
    )

@app.route("/accounting_tracking_categories_delete")
@xero_token_required
def accounting_tracking_categories_delete():
    code = get_code_snippet("TRACKING_CATEGORIES","DELETE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    tracking_category = accounting_api.get_tracking_categories(
            xero_tenant_id
        )
    tracking_category_id = getvalue(tracking_category, "tracking_categories.1.tracking_category_id", "")

    #[TRACKING_CATEGORIES:DELETE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        deleted_tracking_category = accounting_api.delete_tracking_category(
            xero_tenant_id, tracking_category_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Tracking Category deleted."
        json = serialize_model(deleted_tracking_category)
    #[/TRACKING_CATEGORIES:DELETE]

    return render_template(
        "output.html", title="Tracking Categories", code=code, output=output, json=json, len = 0, set="accounting", endpoint="tracking_categories", action="delete"
    )

@app.route("/accounting_tracking_categories_create_options")
@xero_token_required
def accounting_tracking_categories_create_options():
    code = get_code_snippet("TRACKING_OPTIONS","CREATE")

    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    tracking_category = accounting_api.get_tracking_categories(
            xero_tenant_id
        )
    tracking_category_id = getvalue(tracking_category, "tracking_categories.0.tracking_category_id", "")

    #[TRACKING_OPTIONS:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    tracking_option = TrackingOption(
        name = "Foobar" + get_random_num())

    try:
        created_tracking_option = accounting_api.create_tracking_options(
            xero_tenant_id, tracking_category_id, tracking_option
        )

    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Tracking Option created with name {} .".format(
            tracking_option.name
        )
        json = serialize_model(created_tracking_option)
    #[/TRACKING_OPTIONS:CREATE]

    return render_template(
        "output.html", title="Tracking Options", code=code, output=output, json=json, len = 0, set="accounting", endpoint="tracking_categories", action="create_options"
    )

@app.route("/accounting_tracking_categories_update_options")
@xero_token_required
def accounting_tracking_categories_update_options():
    code = get_code_snippet("TRACKING_OPTIONS","UPDATE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    tracking_category = accounting_api.get_tracking_categories(
            xero_tenant_id
        )
    tracking_category_id = getvalue(tracking_category, "tracking_categories.0.tracking_category_id", "")

    tracking_option_id = getvalue(tracking_category, "tracking_categories.0.options.0.tracking_option_id", "")

    tracking_option = TrackingOption(
        name = "Foobar" + get_random_num())

    #[TRACKING_OPTIONS:UPDATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        updated_tracking_option = accounting_api.update_tracking_options(
            xero_tenant_id, tracking_category_id, tracking_option_id, tracking_option
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Tracking Category updated."
        json = serialize_model(updated_tracking_option)
    #[/TRACKING_OPTIONS:UPDATE]

    return render_template(
        "output.html", title="Tracking Options", code=code, output=output, json=json, len = 0, set="accounting", endpoint="tracking_categories", action="update_options"
    )

@app.route("/accounting_tracking_categories_delete_options")
@xero_token_required
def accounting_tracking_categories_delete_options():
    code = get_code_snippet("TRACKING_OPTIONS","DELETE")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    tracking_category = accounting_api.get_tracking_categories(
            xero_tenant_id
        )
    tracking_category_id = getvalue(tracking_category, "tracking_categories.0.tracking_category_id", "")

    tracking_option_id = getvalue(tracking_category, "tracking_categories.0.options.0.tracking_option_id", "")

    #[TRACKING_OPTIONS:DELETE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        deleted_tracking_option = accounting_api.delete_tracking_options(
            xero_tenant_id, tracking_category_id, tracking_option_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Tracking Option deleted."
        json = serialize_model(deleted_tracking_option)
    #[/TRACKING_OPTIONS:DELETE]

    return render_template(
        "output.html", title="Tracking Options", code=code, output=output, json=json, len = 0, set="accounting", endpoint="tracking_categories", action="delete_options"
    )

# USERS TODO
# getUsers x
# getUser
@app.route("/accounting_user_read_all")
@xero_token_required
def accounting_user_read_all():
    code = get_code_snippet("USERS","READ_ALL")

    #[USERS:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    try:
        read_users = accounting_api.get_users(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Users read {} total".format(
            len(read_users.users)
        )
        json = serialize_model(read_users)
    #[/USERS:READ_ALL]

    return render_template(
        "output.html", title="Users", code=code, json=json, output=output, len = 0, set="accounting", endpoint="user", action="read_all"
    )

@app.route("/assets_asset_read_all")
@xero_token_required
def assets_asset_read_all():
    code = get_code_snippet("ASSETS","READ_ALL")

    #[ASSETS:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    asset_api = AssetApi(api_client)

    try:
        read_assets = asset_api.get_assets(
            xero_tenant_id, status=AssetStatusQueryParam.DRAFT
        )
        asset_id = getvalue(read_assets, "items.0.asset_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Assets read first one purchase date {}.".format(
            getvalue(read_assets, "items.0.purchase_date", "")
        )
        json = serialize_model(read_assets)
    #[/ASSETS:READ_ALL]

    return render_template(
        "output.html", title="Assets", code=code, output=output, json=json, len = 0, set="assets", endpoint="asset", action="read_all"
    )

@app.route("/assets_asset_read_one")
@xero_token_required
def assets_asset_read_one():
    code = get_code_snippet("ASSETS","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    asset_api = AssetApi(api_client)

    # READ ALL ASSETS
    try:
        read_assets = asset_api.get_assets(
            xero_tenant_id, status=AssetStatusQueryParam.DRAFT
        )
        asset_id = getvalue(read_assets, "items.0.asset_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[ASSETS:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    asset_api = AssetApi(api_client)

    try:
        read_asset_by_id = asset_api.get_asset_by_id(
            xero_tenant_id, asset_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Asset read with name {}.".format(
            getvalue(read_asset_by_id, "asset_name", "")
        )
        json = serialize_model(read_asset_by_id)
    #[/ASSETS:READ_ONE]

    return render_template(
        "output.html", title="Assets", code=code, output=output, json=json, len = 0, set="assets", endpoint="asset", action="read_one"
    )

@app.route("/assets_asset_create")
@xero_token_required
def assets_asset_create():
    code = get_code_snippet("ASSETS","CREATE")

    #[ASSETS:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    asset_api = AssetApi(api_client)

    asset = Asset(
        asset_number="123" + get_random_num(),
        asset_name=get_random_num(),
        asset_status=AssetStatus.DRAFT,
        disposal_price=20.00,
        purchase_price=100.0,
        accounting_book_value=99.50,
    )
    try:
        created_asset = asset_api.create_asset(
            xero_tenant_id, asset=asset
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Asset created with name {}.".format(
            getvalue(created_asset, "asset_name", "")
        )
        json = serialize_model(created_asset)
    #[/ASSETS:CREATE]

    return render_template(
        "output.html", title="Assets", code=code, output=output, json=json, len = 0, set="assets", endpoint="asset", action="create"
    )

@app.route("/assets_assettype_read_all")
@xero_token_required
def assets_assettype_read_all():
    code = get_code_snippet("ASSET_TYPE","READ_ALL")

    #[ASSET_TYPE:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    asset_api = AssetApi(api_client)

    try:
        read_asset_types = asset_api.get_asset_types(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Assets Types read and first one name {}.".format(
            getvalue(read_asset_types, "0.asset_type_name", "")
        )
        json = serialize_model(read_asset_types)
    #[/ASSET_TYPE:READ_ALL]

    return render_template(
        "output.html", title="Asset Type",  code=code, output=output, json=json, len = 0, set="assets", endpoint="assettype", action="read_all"
    )

@app.route("/assets_assettype_create")
@xero_token_required
def assets_assettype_create():
    code = get_code_snippet("ASSET_TYPE","CREATE")

    #[ASSET_TYPE:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    asset_api = AssetApi(api_client)
    accounting_api = AccountingApi(api_client)

    where = "Type==\"FIXED\"&&Status==\"ACTIVE\""
    read_accounts_1 = accounting_api.get_accounts(
        xero_tenant_id, where=where
    )
    fixed_asset_account_id = getvalue(read_accounts_1, "accounts.0.account_id", "")

    where = "Type==\"EXPENSE\"&&Status==\"ACTIVE\""
    read_accounts_2 = accounting_api.get_accounts(
        xero_tenant_id, where=where
    )
    depreciation_expense_account_id = getvalue(read_accounts_2, "accounts.0.account_id", "")

    where = "Type==\"DEPRECIATN\"&&Status==\"ACTIVE\""
    read_accounts_3 = accounting_api.get_accounts(
        xero_tenant_id, where=where
     )
    accumulated_depreciation_account_id = getvalue(read_accounts_3, "accounts.0.account_id", "")

    book_depreciation_setting = BookDepreciationSetting(
        averaging_method="ActualDays",
        depreciation_calculation_method="None",
        depreciation_rate=10.00,
        depreciation_method="DiminishingValue100",
    )

    asset_type = AssetType(
        asset_type_name="ABC" + get_random_num(),
        fixed_asset_account_id=fixed_asset_account_id,
        depreciation_expense_account_id=depreciation_expense_account_id,
        accumulated_depreciation_account_id=accumulated_depreciation_account_id,
        book_depreciation_setting=book_depreciation_setting,
    )
    try:
        created_asset_type = asset_api.create_asset_type(
            xero_tenant_id, asset_type=asset_type
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Asset Type created with name {}.".format(
            getvalue(created_asset_type, "asset_type_name", "")
        )
        json = serialize_model(created_asset_type)
    #[/ASSET_TYPE:CREATE]

    return render_template(
        "output.html", title="Asset Type",  code=code, output=output, json=json, len = 0, set="assets", endpoint="assettype", action="create"
    )

@app.route("/assets_settings_read")
@xero_token_required
def assets_settings_read():
    code = get_code_snippet("ASSET_SETTINGS","READ")

    #[ASSET_SETTINGS:READ]
    xero_tenant_id = get_xero_tenant_id()
    asset_api = AssetApi(api_client)

    try:
        read_asset_settings = asset_api.get_asset_settings(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "READ all Assets Settings, number {}.".format(
            getvalue(read_asset_settings, "asset_number_sequence", "")
        )
        json = serialize_model(read_asset_settings)
    #[/ASSET_SETTINGS:READ]

    return render_template(
        "output.html", title="Asset Settings", code=code, output=output, json=json, len = 0, set="assets", endpoint="settings", action="read"
    )

@app.route("/projects_project_read_all")
@xero_token_required
def projects_project_read_all():
    code = get_code_snippet("PROJECTS","READ_ALL")

    #[PROJECTS:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)

    try:
        read_projects = project_api.get_projects(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Projects read and found: {}".format(len(read_projects.items)
        )
        json = serialize_model(read_projects)
    #[/PROJECTS:READ_ALL]

    return render_template(
        "output.html", title="Projects", code=code, output=output, json=json, len = 0, set="projects", endpoint="project", action="read_all"
    )

@app.route("/projects_project_read_one")
@xero_token_required
def projects_project_read_one():
    code = get_code_snippet("PROJECTS","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)

    try:
        read_projects = project_api.get_projects(
            xero_tenant_id
        )  # type: Projects
        project_id = getvalue(read_projects, "items.0.project_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[PROJECTS:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)

    try:
        read_project = project_api.get_project(
            xero_tenant_id, project_id=project_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Project read with name {}.".format(
            getvalue(read_project, "name", "")
        )
        json = serialize_model(read_project)
    #[/PROJECTS:READ_ONE]

    return render_template(
        "output.html", title="Projects", code=code, output=output, json=json, len = 0, set="projects", endpoint="project", action="read_one"
    )

@app.route("/projects_project_create")
@xero_token_required
def projects_project_create():
    code = get_code_snippet("PROJECTS","READ_ALL")

    #[PROJECTS:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    # CREATE PROJECT
    # READ CONTACTS FIRST
    try:
        read_contacts = accounting_api.get_contacts(
            xero_tenant_id
        )  # type: Contacts
        contact_id = getvalue(read_contacts, "contacts.0.contact_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[PROJECTS:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)

    project_create_or_update = ProjectCreateOrUpdate(
        contact_id=contact_id,
        name="Foobar",
        estimate_amount=10.00
    )

    try:
        created_project = project_api.create_project(
            xero_tenant_id, project_create_or_update=project_create_or_update
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Project created with name {}.".format(
            getvalue(created_project, "name", "")
        )
        json = serialize_model(created_project)
    #[/PROJECTS:CREATE]

    return render_template(
        "output.html", title="Projects", code=code, output=output, json=json, len = 0, set="projects", endpoint="project", action="create"
    )

@app.route("/projects_project_update")
@xero_token_required
def projects_project_update():
    code = get_code_snippet("PROJECTS","UPDATE")
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)

    # READ PROJECTS
    try:
        read_projects = project_api.get_projects(
            xero_tenant_id
        )  # type: Projects
        project_id = getvalue(read_projects, "items.0.project_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[PROJECTS:UPDATE]
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)

    project_create_or_update = ProjectCreateOrUpdate(
        name="BarFoo"
    )

    try:
        updated_project = project_api.update_project(
            xero_tenant_id, project_id=project_id, project_create_or_update=project_create_or_update
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Project update success"
        json = "204 no response"
    #[/PROJECTS:UPDATE]

    return render_template(
        "output.html", title="Projects", code=code, output=output, json=json, len = 0, set="projects", endpoint="project", action="update"
    )

@app.route("/projects_project_patch")
@xero_token_required
def projects_project_patch():
    code = get_code_snippet("PROJECTS","PATCH")
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)

    # READ PROJECTS
    try:
        read_projects = project_api.get_projects(
            xero_tenant_id
        )  # type: Projects
        project_id = getvalue(read_projects, "items.0.project_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[PROJECTS:PATCH]
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)

    project_patch = ProjectPatch(
        status=ProjectStatus.INPROGRESS
    )

    try:
        patched_project = project_api.patch_project(
            xero_tenant_id, project_id=project_id, project_patch=project_patch
        )
    except AccountingBadRequestException as exception:
        json = "Error: " + exception.reason
        output = jsonify(exception.error_data)
    else:
        output = "Project patch success"
        json = "204 no response"
    #[/PROJECTS:PATCH]

    return render_template(
        "output.html", title="Projects", code=code, output=output, json=json, len = 0, set="projects", endpoint="project", action="patch"
    )

@app.route("/projects_projectuser_read_all")
@xero_token_required
def projects_projectuser_read_all():
    code = get_code_snippet("PROJECT_USERS","READ")

    #[PROJECT_USERS:READ]
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)

    try:
        read_project_users = project_api.get_project_users(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Project Users read and first one name {}".format(
            getvalue(read_project_users, "items.0.name", "")
        )
        json = serialize_model(read_project_users)
    #[/PROJECT_USERS:READ]

    return render_template(
        "output.html",  title="Project Users", code=code, output=output, json=json, len = 0,  set="projects", endpoint="projectuser", action="read_all"
    )

@app.route("/projects_task_read_all")
@xero_token_required
def projects_task_read_all():
    code = get_code_snippet("TASK","READ_ALL")
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)

    # READ TASKS
    # READ PROJECTS
    try:
        read_projects = project_api.get_projects(
            xero_tenant_id
        )  # type: Projects
        project_id = getvalue(read_projects, "items.0.project_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[TASK:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)

    try:
        read_tasks = project_api.get_tasks(
            xero_tenant_id, project_id=project_id
        )
        task_id = getvalue(read_tasks, "items.0.task_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Tasks read and total found: {}".format(read_tasks.pagination.item_count)
        json = serialize_model(read_tasks)
    #[/TASK:READ_ALL]

    return render_template(
        "output.html", title="Tasks", code=code, output=output, json=json, len = 0, set="projects", endpoint="task", action="read_all"
    )

@app.route("/projects_task_read_one")
@xero_token_required
def projects_task_read_one():
    code = get_code_snippet("TASK","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)

    try:
        read_projects = project_api.get_projects(
            xero_tenant_id
        )
        project_id = getvalue(read_projects, "items.0.project_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    try:
        read_tasks = project_api.get_tasks(
            xero_tenant_id, project_id=project_id
        )
        task_id = getvalue(read_tasks, "items.0.task_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[TASK:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)

    try:
        read_task = project_api.get_task(
            xero_tenant_id, project_id=project_id, task_id=task_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Task read with name {}".format(
            getvalue(read_task, "name", "")
        )
        json = serialize_model(read_task)
    #[/TASK:READ_ONE]

    return render_template(
        "output.html", title="Tasks", code=code, output=output, json=json, len = 0, set="projects", endpoint="task", action="read_one"
    )

@app.route("/projects_task_create")
@xero_token_required
def projects_task_create():
    code = get_code_snippet("TASKS","CREATE")
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)

    try:
        read_projects = project_api.get_projects(
            xero_tenant_id
        )
        project_id = getvalue(read_projects, "items.0.project_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[TASKS:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)

    rate = Amount(
        currency=CurrencyCode.AUD,
        value=99.99
    )
    task_create_or_update = TaskCreateOrUpdate(
        name="Deep Fryer",
        rate=rate,
        charge_type=ChargeType.TIME,
        estimate_minutes=120
    )

    try:
        created_task = project_api.create_task(
            xero_tenant_id, project_id, task_create_or_update=task_create_or_update
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Task create success"
        json = serialize_model(created_task)

    #[/TASKS:CREATE]
    return render_template(
        "output.html", title="Tasks", code=code, output=output, json=json, len = 0, set="projects", endpoint="task", action="create"
    )

@app.route("/projects_task_update")
@xero_token_required
def projects_task_update():
    code = get_code_snippet("TASKS","UPDATE")
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)

    try:
        read_projects = project_api.get_projects(
            xero_tenant_id
        )
        project_id = getvalue(read_projects, "items.0.project_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    rate = Amount(
        currency=CurrencyCode.USD,
        value=99.99
    )
    task_create_or_update = TaskCreateOrUpdate(
        name="Deep Fryer",
        rate=rate,
        charge_type=ChargeType.TIME,
        estimate_minutes=120
    )

    try:
        created_task = project_api.create_task(
            xero_tenant_id, project_id, task_create_or_update=task_create_or_update
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    
    try:
        read_tasks = project_api.get_tasks(
            xero_tenant_id, project_id=project_id
        )
        task_id = getvalue(read_tasks, "items.0.task_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[TASKS:UPDATE]
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)

    task_create_or_update = TaskCreateOrUpdate(
        name=get_random_num(),
        rate=read_tasks.items[0].rate,
        charge_type=read_tasks.items[0].charge_type,
        estimate_minutes=read_tasks.items[0].estimate_minutes
    )

    try:
        updated_task = project_api.update_task(
            xero_tenant_id, project_id, task_id, task_create_or_update
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Task update success"
        json = "204 no response"

    #[/TASKS:UPDATE]
    return render_template(
        "output.html", title="Tasks", code=code, output=output, json=json, len = 0, set="projects", endpoint="task", action="update"
    )

@app.route("/projects_task_delete")
@xero_token_required
def projects_task_delete():
    code = get_code_snippet("TASKS","DELETE")
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)

    try:
        read_projects = project_api.get_projects(
            xero_tenant_id
        )
        project_id = getvalue(read_projects, "items.0.project_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    rate = Amount(
        currency=CurrencyCode.USD,
        value=99.99
    )
    task_create_or_update = TaskCreateOrUpdate(
        name="Deep Fryer",
        rate=rate,
        charge_type=ChargeType.TIME,
        estimate_minutes=120
    )

    try:
        created_task = project_api.create_task(
            xero_tenant_id, project_id, task_create_or_update=task_create_or_update
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    
    try:
        read_tasks = project_api.get_tasks(
            xero_tenant_id, project_id=project_id
        )
        task_id = getvalue(read_tasks, "items.0.task_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[TASKS:DELETE]
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)

    try:
        deleted_task = project_api.delete_task(
            xero_tenant_id, project_id, task_id
        )
    except AccountingBadRequestException as exception:
        # If you are encountering {"Message":"A validation exception occurred"}
        # Note that if the task has a service associated or has a status INVOICED, it will not be removed.
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Task delete success"
        json = "204 no response"

    #[/TASKS:DELETE]
    return render_template(
        "output.html", title="Tasks", code=code, output=output, json=json, len = 0, set="projects", endpoint="task", action="delete"
    )

@app.route("/projects_time_read_all")
@xero_token_required
def projects_time_read_all():
    code = get_code_snippet("TIME","READ_ALL")
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)

    # READ PROJECTS
    try:
        read_projects = project_api.get_projects(
            xero_tenant_id
        )  # type: Projects
        project_id = getvalue(read_projects, "items.0.project_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[TIME:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)

    try:
        read_time_entries = project_api.get_time_entries(
            xero_tenant_id, project_id=project_id
        )
        time_entry_id = getvalue(read_time_entries, "items.0.time_entry_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Time Entries read and the first one description {}.".format(
            getvalue(read_time_entries, "items.0.description", "")
        )
        json = serialize_model(read_time_entries)
    #[/TIME:READ_ALL]

    return render_template(
        "output.html", title="Time", code=code, output=output, json=json, len = 0, set="projects", endpoint="time", action="read_all"
    )

@app.route("/projects_time_read_one")
@xero_token_required
def projects_time_read_one():
    code = get_code_snippet("TIME","READ_ONE")
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)

    # READ PROJECTS
    try:
        read_projects = project_api.get_projects(
            xero_tenant_id
        )  # type: Projects
        project_id = getvalue(read_projects, "items.0.project_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    try:
        read_time_entries = project_api.get_time_entries(
            xero_tenant_id, project_id=project_id
        )
        time_entry_id = getvalue(read_time_entries, "items.0.time_entry_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[TIME:READ_ONE]
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)

    try:
        read_time_entry = project_api.get_time_entry(
            xero_tenant_id, project_id=project_id, time_entry_id=time_entry_id
        )  # type: TimeEntries
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Time Entry read one and the description is {}".format(
            getvalue(read_time_entry, "description", "")
        )
        json = serialize_model(read_time_entry)
    #[/TIME:READ_ONE]

    return render_template(
        "output.html", title="Time", code=code, output=output, json=json, len = 0, set="projects", endpoint="time", action="read_one"
    )

@app.route("/projects_time_create")
@xero_token_required
def projects_time_create():
    code = get_code_snippet("TIME","CREATE")

    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)

    # READ PROJECTS
    try:
        read_projects = project_api.get_projects(
            xero_tenant_id
        )  # type: Projects
        project_id = getvalue(read_projects, "items.0.project_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    # READ PROJECT USERS
    try:
        read_project_users = project_api.get_project_users(
            xero_tenant_id
        )  # type: ProjectUsers
        project_user_id = getvalue(read_project_users, "items.0.user_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    # READ TASKS
    try:
        read_tasks = project_api.get_tasks(
            xero_tenant_id, project_id=project_id
        )  # type: Tasks
        task_id = getvalue(read_tasks, "items.0.task_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[TIME:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    project_api = ProjectApi(api_client)

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
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Time Entry created with description {}".format(
            getvalue(create_time_entry, "description", "")
        )
        json = serialize_model(create_time_entry)
    #[/TIME:CREATE]

    return render_template(
        "output.html", title="Time", code=code, output=output, json=json, len = 0, set="projects", endpoint="time", action="create"
    )

@app.route("/payroll_au_employee_read_all")
@xero_token_required
def payroll_au_employee_read_all():
    code = get_code_snippet("EMPLOYEES","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrollau_api = PayrollAuApi(api_client)
    accounting_api = AccountingApi(api_client)

    #[EMPLOYEES:READ_ALL]
    try:
        read_employees = payrollau_api.get_employees(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Employees read all - found: {}".format(len(read_employees.employees))
        json = serialize_model(read_employees)
    #[/EMPLOYEES:READ_ALL]

    return render_template(
        "output.html", title="Employees", code=code, output=output, json=json, len = 0, set="payroll_au", endpoint="employee", action="read_all"
    )

@app.route("/payroll_au_employee_read_one")
@xero_token_required
def payroll_au_employee_read_one():
    code = get_code_snippet("EMPLOYEES","READ_ONE")

    xero_tenant_id = get_xero_tenant_id()
    payrollau_api = PayrollAuApi(api_client)
    accounting_api = AccountingApi(api_client)

    try:
        read_employees = payrollau_api.get_employees(
            xero_tenant_id
        )
        employee_id = getvalue(read_employees, "employees.0.employee_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[EMPLOYEES:READ_ONE]
    try:
         read_employee = payrollau_api.get_employee(
             xero_tenant_id, employee_id
         )
    except AccountingBadRequestException as exception:
         output = "Error: " + exception.reason
         json = jsonify(exception.error_data)
    else:
        output = "Employee read Classification: {}".format(
            getvalue(read_employee, "employees.0.classification", "")
        )
        json = serialize_model(read_employee)
    #[/EMPLOYEES:READ_ONE]

    return render_template(
        "output.html", title="Employee", code=code, output=output, json=json, len = 0, set="payroll_au", endpoint="employee", action="read_one"
    )

@app.route("/payroll_au_employee_create")
@xero_token_required
def payroll_au_employee_create():
    code = get_code_snippet("EMPLOYEES","READ_ALL")

    #[EMPLOYEES:CREATE]
    xero_tenant_id = get_xero_tenant_id()
    payrollau_api = PayrollAuApi(api_client)

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

    employees = [employee]
    try:
        create_employees = payrollau_api.create_employee(
            xero_tenant_id, employee=employees
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Employee created with first name {}".format(
            getvalue(create_employees, "employees.0.first_name", "")
        )
        json = serialize_model(create_employees)
    #[/EMPLOYEES:CREATE]

    return render_template(
        "output.html", title="Employees", code=code, output=output, json=json, len = 0, set="payroll_au", endpoint="employee", action="create"
    )

@app.route("/payroll_au_leave_application_read_all")
@xero_token_required
def payroll_au_leave_application_read_all():
    code = get_code_snippet("LEAVE_APPLICATION","READ_ALL")

    #[LEAVE_APPLICATION:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    payrollau_api = PayrollAuApi(api_client)

    try:
        read_leave_applications = payrollau_api.get_leave_applications(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Leave applications read and first id {}".format(
            getvalue(read_leave_applications, "leave_applications.0.leave_application_id", "")
        )
        json = serialize_model(read_leave_applications)
    #[/LEAVE_APPLICATION:READ_ALL]

    return render_template(
        "output.html", title="Leave Applications", code=code, output=output, json=json, len = 0, set="payroll_au", endpoint="leave_application", action="read_all"
    )

@app.route("/payroll_au_pay_item_read_all")
@xero_token_required
def payroll_au_pay_item_read_all():
    code = get_code_snippet("PAY_ITEM","READ_ALL")

    #[PAY_ITEM:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    payrollau_api = PayrollAuApi(api_client)

    try:
        read_pay_items = payrollau_api.get_pay_items(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Pay items read all and found: {}".format(
            getvalue(read_pay_items, "pay_items.0.earnings_rates.0.name", "")
        )
        json = serialize_model(read_pay_items)
    #[/PAY_ITEM:READ_ALL]

    return render_template(
        "output.html", title="Pay Items", code=code, output=output, json=json, len = 0, set="payroll_au", endpoint="pay_item", action="read_all"
    )

@app.route("/payroll_au_payroll_calendar_read_all")
@xero_token_required
def payroll_au_payroll_calendar_read_all():
    code = get_code_snippet("PAYROLL_CALENDAR","READ_ALL")

    #[PAYROLL_CALENDAR:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    payrollau_api = PayrollAuApi(api_client)

    try:
        read_payroll_calendars = payrollau_api.get_payroll_calendars(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Payroll calendars all read and found {}".format(
            len(read_payroll_calendars.payroll_calendars)
        )
        json = serialize_model(read_payroll_calendars)
    #[/PAYROLL_CALENDAR:READ_ALL]

    return render_template(
        "output.html", title="Payroll Calendars", code=code, output=output, json=json, len = 0, set="payroll_au", endpoint="payroll_calendar", action="read_all"
    )

@app.route("/payroll_au_pay_run_read_all")
@xero_token_required
def payroll_au_pay_run_read_all():
    code = get_code_snippet("PAY_RUN","READ_ALL")

    #[PAY_RUN:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    payrollau_api = PayrollAuApi(api_client)

    try:
        read_pay_runs = payrollau_api.get_pay_runs(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Pay runs read all and found {}".format(
            getvalue(read_pay_runs, "pay_runs.0.pay_run_id", "")
        )
        json = serialize_model(read_pay_runs)
    #[/PAY_RUN:READ_ALL]

    return render_template(
        "output.html", title="PayRuns", code=code, output=output, json=json, len = 0, set="payroll_au", endpoint="pay_run", action="read_all"
    )

@app.route("/payroll_au_pay_slip_read_all")
@xero_token_required
def payroll_au_pay_slip_read_all():
    code = get_code_snippet("PAY_SLIP","READ_ALL")

    #[PAY_SLIP:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    payrollau_api = PayrollAuApi(api_client)

    # READ ALL PAY RUNS to get pay_run_id
    try:
        read_pay_runs = payrollau_api.get_pay_runs(
            xero_tenant_id
        )
        pay_run_id = getvalue(read_pay_runs, "pay_runs.0.pay_run_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    # READ PAY RUN DETAILS to get payslip_id
    try:
        read_pay_run = payrollau_api.get_pay_run(
            xero_tenant_id, pay_run_id=pay_run_id
        )
        payslip_id = getvalue(read_pay_run, "pay_runs.0.payslips.0.payslip_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    # READ PAYSLIP DETAILS
    try:
        read_pay_slip = payrollau_api.get_payslip(
            xero_tenant_id, payslip_id=payslip_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Pay slip read for first one name {}".format(
            getvalue(read_pay_slip, "payslip.first_name", "")
        )
        json = serialize_model(read_pay_slip)

    #[/PAY_SLIP:READ_ALL]

    return render_template(
        "output.html", title="PaySlips", code=code, output=output, json=json, len = 0, set="payroll_au", endpoint="pay_slip", action="read_all"
    )

@app.route("/payroll_au_settings_read_all")
@xero_token_required
def payroll_au_settings_read_all():
    code = get_code_snippet("SETTINGS","READ_ALL")

    #[SETTINGS:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    payrollau_api = PayrollAuApi(api_client)

    try:
        read_settings = payrollau_api.get_settings(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Settings read all and the first account name {}".format(
            getvalue(read_settings, "settings.accounts.0.name", "")
        )
        json = serialize_model(read_settings)
    #[/SETTINGS:READ_ALL]

    return render_template(
        "output.html", title="Settings", code=code, output=output, json=json, len = 0, set="payroll_au", endpoint="settings", action="read_all"
    )

@app.route("/payroll_au_superfund_read_all")
@xero_token_required
def payroll_au_superfund_read_all():
    code = get_code_snippet("SUPERFUND","READ_ALL")

    #[SUPERFUND:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    payrollau_api = PayrollAuApi(api_client)

    try:
        read_superfund = payrollau_api.get_superfunds(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "READ all SuperFund - first name {}.".format(
            getvalue(read_superfund, "super_funds.0.name", "")
        )
        json = serialize_model(read_superfund)
    #[/SUPERFUND:READ_ALL]

    return render_template(
        "output.html", title="SuperFunds", code=code, output=output, json=json, len = 0, set="payroll_au", endpoint="superfund", action="read_all"
    )

@app.route("/payroll_au_superfund_product_read_all")
@xero_token_required
def payroll_au_superfund_product_read_all():
    code = get_code_snippet("SUPERFUND_PRODUCT","READ_ALL")

    #[SUPERFUND_PRODUCT:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    payrollau_api = PayrollAuApi(api_client)

    try:
        read_superfund_products = payrollau_api.get_superfund_products(
            xero_tenant_id, usi="16517650366001"
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "SuperFund Product read all and first ABN {}".format(
            getvalue(read_superfund_products, "super_fund_products.0.abn", "")
        )
        json = serialize_model(read_superfund_products)
    #[/SUPERFUND_PRODUCT:READ_ALL]

    return render_template(
        "output.html", title="SuperFund Products", code=code, output=output, json=json, len = 0, set="payroll_au", endpoint="superfund_product", action="read_all"
    )

@app.route("/payroll_au_timesheet_read_all")
@xero_token_required
def payroll_au_timesheet_read_all():
    code = get_code_snippet("TIMESHEET","READ_ALL")

    #[TIMESHEET:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    payrollau_api = PayrollAuApi(api_client)

    try:
        read_timeshets = payrollau_api.get_timesheets(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Timesheets read all and first employee id {}".format(
            getvalue(read_timeshets, "timesheets.0.employee_id", "")
        )
        json = serialize_model(read_timeshets)
    #[/TIMESHEET:READ_ALL]

    return render_template(
        "output.html", title="Timesheets", code=code, output=output, json=json, len = 0, set="payroll_au", endpoint="timesheet", action="read_all"
    )


@app.route("/payroll_nz_employee_nz_read_all")
@xero_token_required
def payroll_nz_employee_nz_read_all():
    code = get_code_snippet("EMPLOYEE_NZ","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrollnz_api = PayrollNzApi(api_client)
    accounting_api = AccountingApi(api_client)

    #[EMPLOYEE_NZ:READ_ALL]
    try:
        read_employees = payrollnz_api.get_employees(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Employees read all - found: {}".format(read_employees.pagination.item_count)
        json = serialize_model(read_employees)
    #[/EMPLOYEE_NZ:READ_ALL]

    return render_template(
        "output.html", title="Employees", code=code, output=output, json=json, len = 0, set="payroll_nz", endpoint="employee_nz", action="read_all"
    )

@app.route("/payroll_nz_employee_nz_read_one")
@xero_token_required
def payroll_nz_employee_nz_read_one():
    code = get_code_snippet("EMPLOYEE_NZ","READ_ONE")

    xero_tenant_id = get_xero_tenant_id()
    payrollnz_api = PayrollNzApi(api_client)

    read_employees = payrollnz_api.get_employees(
        xero_tenant_id
    )
    employee_id = getvalue(read_employees, "employees.0.employee_id", "")

    #[EMPLOYEE_NZ:READ_ONE]
    try:
        read_employee = payrollnz_api.get_employee(
            xero_tenant_id, employee_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Employees read one - first name: {}".format(
            getvalue(read_employee, "employee.first_name", "")
        )
        json = serialize_model(read_employee)
    #[/EMPLOYEE_NZ:READ_ONE]

    return render_template(
        "output.html", title="Employees", code=code, output=output, json=json, len = 0, set="payroll_nz", endpoint="employee_nz", action="read_one"
    )

@app.route("/payroll_nz_employment_nz_create")
@xero_token_required
def payroll_nz_employment_nz_create():
    code = get_code_snippet("EMPLOYMENT_NZ","CREATE")

    xero_tenant_id = get_xero_tenant_id()
    payrollnz_api = PayrollNzApi(api_client)

    read_employees = payrollnz_api.get_employees(
        xero_tenant_id
    )
    employee_id = getvalue(read_employees, "employees.0.employee_id", "")

    read_pay_run_calendars = payrollnz_api.get_pay_run_calendars(
        xero_tenant_id
    )
    payroll_calendar_id = getvalue(read_pay_run_calendars, "pay_run_calendars.0.payroll_calendar_id", "")

    #[EMPLOYMENT_NZ:CREATE]
    employment = Employment(
        payroll_calendar_id=payroll_calendar_id,
        start_date=dateutil.parser.parse("2020-1-15T00:00:00Z"),
    )
    try:
        created_employment = payrollnz_api.create_employment(
            xero_tenant_id, employee_id, employment
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Employees read one - first name: {}".format(
            getvalue(created_employment, "employee.first_name", "")
        )
        json = serialize_model(created_employment)
    #[/EMPLOYMENT_NZ:CREATE]

    return render_template(
        "output.html", title="Employment", code=code, output=output, json=json, len = 0, set="payroll_nz", endpoint="employment_nz", action="create"
    )

@app.route("/payroll_nz_employee_tax_nz_read")
@xero_token_required
def payroll_nz_employee_tax_nz_read():
    code = get_code_snippet("EMPLOYEE_TAX_NZ","READ")

    xero_tenant_id = get_xero_tenant_id()
    payrollnz_api = PayrollNzApi(api_client)

    read_employees = payrollnz_api.get_employees(
        xero_tenant_id
    )
    employee_id = getvalue(read_employees, "employees.0.employee_id", "")

    #[EMPLOYEE_TAX_NZ:READ]
    try:
        read_employee_tax = payrollnz_api.get_employee_tax(
            xero_tenant_id, employee_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Employees Tax read - ird number: {}".format(
            getvalue(read_employee_tax, "employee_tax.ird_number", "")
        )
        json = serialize_model(read_employee_tax)
    #[/EMPLOYEE_TAX_NZ:READ]

    return render_template(
        "output.html", title="Employee Tax", code=code, output=output, json=json, len = 0, set="payroll_nz", endpoint="employee_tax_nz", action="read"
    )

@app.route("/payroll_nz_employee_leave_setup_nz_read")
@xero_token_required
def payroll_nz_employee_leave_setup_nz_read():
    code = get_code_snippet("EMPLOYEE_LEAVE_SETUP_NZ","CREATE")

    xero_tenant_id = get_xero_tenant_id()
    payrollnz_api = PayrollNzApi(api_client)

    address = Address(
        address_line1 = "101 Green St",
        city = "Milton Keynes",
        post_code = "4351",
        country_name = "United Kingdom"
    )

    employee = Employee(
        first_name = "Jack",
        last_name = "Jones",
        date_of_birth = dateutil.parser.parse("2000-03-01T00:00:00Z"),
        email = "jack@jones" + get_random_num() + ".com",
        address = address,
        gender = "M",
        phone_number = "415-555-1212",
        start_date = dateutil.parser.parse("2020-10-01T00:00:00Z")
    )

    created_employee = payrollnz_api.create_employee(
        xero_tenant_id, employee
    )
    employee_id = getvalue(created_employee, "employee.employee_id", "")

    #[EMPLOYEE_LEAVE_SETUP_NZ:CREATE]
    employee_leave_setup = EmployeeLeaveSetup(
        annual_leave_opening_balance = 100.0,
        sick_leave_opening_balance = 10.0,
        sick_leave_hours_to_accrue_annually = 20.0,
        holiday_pay_opening_balance = 10.0
    )

    try:
        read_employee_leave = payrollnz_api.create_employee_leave_setup(
            xero_tenant_id, employee_id, employee_leave_setup
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "SuperFund Product read all and first ABN {}".format(
            getvalue(read_employee_leave, "leave.0.description", "")
        )
        json = serialize_model(read_employee_leave)
    #[/EMPLOYEE_LEAVE_SETUP_NZ:CREATE]

    return render_template(
        "output.html", title="Employee Leave", code=code, output=output, json=json, len = 0, set="payroll_nz", endpoint="employee_leave_nz", action="read"
    )

@app.route("/payroll_nz_employee_leave_nz_read")
@xero_token_required
def payroll_nz_employee_leave_nz_read():
    code = get_code_snippet("EMPLOYEE_LEAVE_NZ","READ")

    xero_tenant_id = get_xero_tenant_id()
    payrollnz_api = PayrollNzApi(api_client)

    read_employees = payrollnz_api.get_employees(
        xero_tenant_id
    )
    employee_id = getvalue(read_employees, "employees.0.employee_id", "")

    #[EMPLOYEE_LEAVE_NZ:READ]
    try:
        read_employee_leave = payrollnz_api.get_employee_leaves(
            xero_tenant_id, employee_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "SuperFund Product read all and first ABN {}".format(
            getvalue(read_employee_leave, "leave.0.description", "")
        )
        json = serialize_model(read_employee_leave)
    #[/EMPLOYEE_LEAVE_NZ:READ]

    return render_template(
        "output.html", title="Employee Leave", code=code, output=output, json=json, len = 0, set="payroll_nz", endpoint="employee_leave_nz", action="read"
    )

@app.route("/payroll_nz_employee_leave_balances_nz_read")
@xero_token_required
def payroll_nz_employee_leave_balances_nz_read():
    code = get_code_snippet("EMPLOYEE_LEAVE_BALANCES_NZ","READ")

    xero_tenant_id = get_xero_tenant_id()
    payrollnz_api = PayrollNzApi(api_client)

    read_employees = payrollnz_api.get_employees(
        xero_tenant_id
    )
    employee_id = getvalue(read_employees, "employees.0.employee_id", "")

    #[EMPLOYEE_LEAVE_BALANCES_NZ:READ]
    try:
        read_employee_leave_balances = payrollnz_api.get_employee_leave_balances(
            xero_tenant_id, employee_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Employee Leave Balances - first name: {}".format(
            getvalue(read_employee_leave_balances, "leave_balances.0.name", "")
        )
        json = serialize_model(read_employee_leave_balances)
    #[/EMPLOYEE_LEAVE_BALANCES_NZ:READ]

    return render_template(
        "output.html", title="Employee Leave Balances", code=code, output=output, json=json, len = 0, set="payroll_nz", endpoint="employee_leave_balances_nz", action="read"
    )

@app.route("/payroll_nz_employee_payment_method_nz_read")
@xero_token_required
def payroll_nz_employee_payment_method_nz_read():
    code = get_code_snippet("EMPLOYEE_PAYMENT_METHOD_NZ","READ")

    xero_tenant_id = get_xero_tenant_id()
    payrollnz_api = PayrollNzApi(api_client)

    read_employees = payrollnz_api.get_employees(
        xero_tenant_id
    )
    employee_id = getvalue(read_employees, "employees.0.employee_id", "")

    #[EMPLOYEE_PAYMENT_METHOD_NZ:READ]
    try:
        read_employee_payment_method = payrollnz_api.get_employee_payment_method(
            xero_tenant_id, employee_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Employee Payment Methods - first account name: {}".format(
            getvalue(read_employee_payment_method, "payment_method.bank_accounts.0.account_name", "")
        )

        json = serialize_model(read_employee_payment_method)
    #[/EMPLOYEE_PAYMENT_METHOD_NZ:READ]

    return render_template(
        "output.html", title="Employee Payment Method", code=code, output=output, json=json, len = 0, set="payroll_nz", endpoint="employee_payment_method_nz", action="read"
    )

@app.route("/payroll_nz_pay_run_calendars_nz_read_all")
@xero_token_required
def payroll_nz_pay_run_calendars_nz_read_all():
    code = get_code_snippet("PAY_RUN_CALENDARS_NZ","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrollnz_api = PayrollNzApi(api_client)

    #[PAY_RUN_CALENDARS_NZ:READ_ALL]
    try:
        read_all_pay_run_calendars = payrollnz_api.get_pay_run_calendars(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Payrun Calendars - total: {}".format(
            getvalue(read_all_pay_run_calendars, "pagination.item_count", "")
        )
        json = serialize_model(read_all_pay_run_calendars)
    #[/PAY_RUN_CALENDARS_NZ:READ_ALL]

    return render_template(
        "output.html", title="Payrun Calendars", code=code, output=output, json=json, len = 0, set="payroll_nz", endpoint="pay_run_calendars_nz", action="read_all"
    )

@app.route("/payroll_nz_employee_salary_and_wages_nz_read_all")
@xero_token_required
def payroll_nz_employee_salary_and_wages_nz_read_all():
    code = get_code_snippet("EMPLOYEE_SALARY_AND_WAGES_NZ","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrollnz_api = PayrollNzApi(api_client)

    read_employees = payrollnz_api.get_employees(
        xero_tenant_id
    )
    employee_id = getvalue(read_employees, "employees.0.employee_id", "")

    #[EMPLOYEE_SALARY_AND_WAGES_NZ:READ_ALL]
    try:
        read_all_employee_salary_and_wages = payrollnz_api.get_employee_salary_and_wages(
            xero_tenant_id, employee_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Employee Salary & Wages - total: {}".format(
            getvalue(read_all_employee_salary_and_wages, "pagination.item_count", "")
        )
        json = serialize_model(read_all_employee_salary_and_wages)
    #[/EMPLOYEE_SALARY_AND_WAGES_NZ:READ_ALL]

    return render_template(
        "output.html", title="Employee Salary and Wages", code=code, output=output, json=json, len = 0, set="payroll_nz", endpoint="employee_salary_and_wages_nz", action="read_all"
    )

@app.route("/payroll_nz_employee_opening_balances_nz_read")
@xero_token_required
def payroll_nz_employee_opening_balances_nz_read():
    code = get_code_snippet("EMPLOYEE_OPENING_BALANCES_NZ","READ")

    xero_tenant_id = get_xero_tenant_id()
    payrollnz_api = PayrollNzApi(api_client)

    read_employees = payrollnz_api.get_employees(
        xero_tenant_id
    )
    employee_id = getvalue(read_employees, "employees.0.employee_id", "")

    #[EMPLOYEE_OPENING_BALANCES_NZ:READ]
    try:
        read_employee_opening_balances = payrollnz_api.get_employee_opening_balances(
            xero_tenant_id, employee_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Employee Opening Balances - total: {}".format(
            getvalue(read_employee_opening_balances, "pagination.item_count", "")
        )
        json = serialize_model(read_employee_opening_balances)
    #[/EMPLOYEE_OPENING_BALANCES_NZ:READ]

    return render_template(
        "output.html", title="Employee Opening Balances", code=code, output=output, json=json, len = 0, set="payroll_nz", endpoint="employee_opening_balances_nz", action="read"
    )

@app.route("/payroll_nz_employee_leave_periods_nz_read")
@xero_token_required
def payroll_nz_employee_leave_periods_nz_read():
    code = get_code_snippet("EMPLOYEE_LEAVE_PERIODS_NZ","READ")

    xero_tenant_id = get_xero_tenant_id()
    payrollnz_api = PayrollNzApi(api_client)

    read_employees = payrollnz_api.get_employees(
        xero_tenant_id
    )
    employee_id = getvalue(read_employees, "employees.0.employee_id", "")

    #[EMPLOYEE_LEAVE_PERIODS_NZ:READ]
    start_date = dateutil.parser.parse("2020-03-01T00:00:00Z")
    end_date = dateutil.parser.parse("2020-04-26T00:00:00Z")

    try:
        read_employee_leave_periods = payrollnz_api.get_employee_leave_periods(
            xero_tenant_id, employee_id, start_date=start_date, end_date=end_date
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Employee Leave Periods - total: {}".format(
            getvalue(read_employee_leave_periods, "pagination.item_count", "")
        )
        json = serialize_model(read_employee_leave_periods)
    #[/EMPLOYEE_LEAVE_PERIODS_NZ:READ]

    return render_template(
        "output.html", title="Employee Leave Periods", code=code, output=output, json=json, len = 0, set="payroll_nz", endpoint="employee_leave_periods_nz", action="read"
    )

@app.route("/payroll_nz_employee_leave_types_nz_read")
@xero_token_required
def payroll_nz_employee_leave_types_nz_read():
    code = get_code_snippet("EMPLOYEE_LEAVE_TYPES_NZ","READ")

    xero_tenant_id = get_xero_tenant_id()
    payrollnz_api = PayrollNzApi(api_client)

    read_employees = payrollnz_api.get_employees(
        xero_tenant_id
    )
    employee_id = getvalue(read_employees, "employees.0.employee_id", "")

    #[EMPLOYEE_LEAVE_TYPES_NZ:READ]
    try:
        read_employee_leave_types = payrollnz_api.get_employee_leave_types(
            xero_tenant_id, employee_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Employee Leave Types - first schedule of accrual: {}".format(
            getvalue(read_employee_leave_types, "leave_types.0.schedule_of_accrual", "")
        )
        json = serialize_model(read_employee_leave_types)
    #[/EMPLOYEE_LEAVE_TYPES_NZ:READ]

    return render_template(
        "output.html", title="Employee Leave Types", code=code, output=output, json=json, len = 0, set="payroll_nz", endpoint="employee_leave_types_nz", action="read"
    )

@app.route("/payroll_nz_employee_pay_templates_nz_read_all")
@xero_token_required
def payroll_nz_employee_pay_templates_nz_read_all():
    code = get_code_snippet("EMPLOYEE_PAY_TEMPLATES_NZ","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrollnz_api = PayrollNzApi(api_client)

    read_employees = payrollnz_api.get_employees(
        xero_tenant_id
    )
    employee_id = getvalue(read_employees, "employees.0.employee_id", "")

    #[EMPLOYEE_PAY_TEMPLATES_NZ:READ_ALL]
    try:
        read_all_employee_pay_templates = payrollnz_api.get_employee_pay_templates(
            xero_tenant_id, employee_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Employee Pay Templates - total: {}".format(
            getvalue(read_all_employee_pay_templates, "pagination.item_count", "")
        )
        json = serialize_model(read_all_employee_pay_templates)
    #[/EMPLOYEE_PAY_TEMPLATES_NZ:READ_ALL]

    return render_template(
        "output.html", title="Employee Pay Templates", code=code, output=output, json=json, len = 0, set="payroll_nz", endpoint="employee_pay_templates_nz", action="read_all"
    )

@app.route("/payroll_nz_earnings_rates_nz_read_all")
@xero_token_required
def payroll_nz_earnings_rates_nz_read_all():
    code = get_code_snippet("EARNINGS_RATES_NZ","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrollnz_api = PayrollNzApi(api_client)

    #[EARNINGS_RATES_NZ:READ_ALL]
    try:
        read_all_earnings_rates = payrollnz_api.get_earnings_rates(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Earnings Rates - total: {}".format(
            getvalue(read_all_earnings_rates, "pagination.item_count", "")
        )
        json = serialize_model(read_all_earnings_rates)
    #[/EARNINGS_RATES_NZ:READ_ALL]

    return render_template(
        "output.html", title="Earnings Rates", code=code, output=output, json=json, len = 0, set="payroll_nz", endpoint="earnings_rates_nz", action="read_all"
    )

@app.route("/payroll_nz_deductions_nz_read_all")
@xero_token_required
def payroll_nz_deductions_nz_read_all():
    code = get_code_snippet("DEDUCTIONS_NZ","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrollnz_api = PayrollNzApi(api_client)

    #[DEDUCTIONS_NZ:READ_ALL]
    try:
        read_all_deductions = payrollnz_api.get_deductions(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Deductions - total: {}".format(
            getvalue(read_all_deductions, "pagination.item_count", "")
        )
        json = serialize_model(read_all_deductions)
    #[/DEDUCTIONS_NZ:READ_ALL]

    return render_template(
        "output.html", title="Deductions", code=code, output=output, json=json, len = 0, set="payroll_nz", endpoint="deductions_nz", action="read_all"
    )

@app.route("/payroll_nz_leave_types_nz_read_all")
@xero_token_required
def payroll_nz_leave_types_nz_read_all():
    code = get_code_snippet("LEAVE_TYPES_NZ","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrollnz_api = PayrollNzApi(api_client)

    #[LEAVE_TYPES_NZ:READ_ALL]
    try:
        read_all_leave_types = payrollnz_api.get_leave_types(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Leave types - total: {}".format(
            getvalue(read_all_leave_types, "pagination.item_count", "")
        )
        json = serialize_model(read_all_leave_types)
    #[/LEAVE_TYPES_NZ:READ_ALL]

    return render_template(
        "output.html", title="Leave Types", code=code, output=output, json=json, len = 0, set="payroll_nz", endpoint="leave_types_nz", action="read_all"
    )

@app.route("/payroll_nz_reimbursements_nz_read_all")
@xero_token_required
def payroll_nz_reimbursements_nz_read_all():
    code = get_code_snippet("REIMBURSEMENTS_NZ","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrollnz_api = PayrollNzApi(api_client)

    #[REIMBURSEMENTS_NZ:READ_ALL]
    try:
        read_all_reimbursements = payrollnz_api.get_reimbursements(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Reimbursements - total: {}".format(
            getvalue(read_all_reimbursements, "pagination.item_count", "")
        )
        json = serialize_model(read_all_reimbursements)
    #[/REIMBURSEMENTS_NZ:READ_ALL]

    return render_template(
        "output.html", title="Reimbursements", code=code, output=output, json=json, len = 0, set="payroll_nz", endpoint="reimbursements_nz", action="read_all"
    )


@app.route("/payroll_nz_statutory_deductions_nz_read_all")
@xero_token_required
def payroll_nz_statutory_deductions_nz_read_all():
    code = get_code_snippet("STATUTORY_DEDUCTIONS_NZ","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrollnz_api = PayrollNzApi(api_client)

    #[STATUTORY_DEDUCTIONS_NZ:READ_ALL]
    try:
        read_all_statutory_deductions = payrollnz_api.get_statutory_deductions(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Statutory Deductions - total: {}".format(
            getvalue(read_all_statutory_deductions, "pagination.item_count", "")
        )
        json = serialize_model(read_all_statutory_deductions)
    #[/STATUTORY_DEDUCTIONS_NZ:READ_ALL]

    return render_template(
        "output.html", title="Statutory Deductions", code=code, output=output, json=json, len = 0, set="payroll_nz", endpoint="statutory_deductions_nz", action="read_all"
    )

@app.route("/payroll_nz_superannuation_nz_read_all")
@xero_token_required
def payroll_nz_superannuation_nz_read_all():
    code = get_code_snippet("SUPERANNUATION_NZ","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrollnz_api = PayrollNzApi(api_client)

    #[SUPERANNUATION_NZ:READ_ALL]
    try:
        read_all_superannuations = payrollnz_api.get_superannuations(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Superannuation - total: {}".format(
            getvalue(read_all_superannuations, "pagination.item_count", "")
        )
        json = serialize_model(read_all_superannuations)
    #[/SUPERANNUATION_NZ:READ_ALL]

    return render_template(
        "output.html", title="Superannuation", code=code, output=output, json=json, len = 0, set="payroll_nz", endpoint="superannuations_nz", action="read_all"
    )

@app.route("/payroll_nz_pay_runs_nz_read_all")
@xero_token_required
def payroll_nz_pay_runs_nz_read_all():
    code = get_code_snippet("PAY_RUNS_NZ","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrollnz_api = PayrollNzApi(api_client)

    #[PAY_RUNS_NZ:READ_ALL]
    try:
        read_all_pay_runs = payrollnz_api.get_pay_runs(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Payruns - total: {}".format(
            getvalue(read_all_pay_runs, "pagination.item_count", "")
        )
        json = serialize_model(read_all_pay_runs)
    #[/PAY_RUNS_NZ:READ_ALL]

    return render_template(
        "output.html", title="Payruns", code=code, output=output, json=json, len = 0, set="payroll_nz", endpoint="pay_runs_nz", action="read_all"
    )

@app.route("/payroll_nz_pay_slips_nz_read_all")
@xero_token_required
def payroll_nz_pay_slips_nz_read_all():
    code = get_code_snippet("PAY_SLIPS_NZ","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrollnz_api = PayrollNzApi(api_client)

    read_all_pay_runs = payrollnz_api.get_pay_runs(
        xero_tenant_id
    )
    pay_run_id = getvalue(read_all_pay_runs, "pay_runs.0.pay_run_id", "")

    #[PAY_SLIPS_NZ:READ_ALL]
    try:
        read_all_pay_slips = payrollnz_api.get_pay_slips(
            xero_tenant_id, pay_run_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Payslips - total: {}".format(
            getvalue(read_all_pay_slips, "pagination.item_count", "")
        )
        json = serialize_model(read_all_pay_slips)
    #[/PAY_SLIPS_NZ:READ_ALL]

    return render_template(
        "output.html", title="Payslips", code=code, output=output, json=json, len = 0, set="payroll_nz", endpoint="pay_slips_nz", action="read_all"
    )

@app.route("/payroll_nz_timesheets_nz_read_all")
@xero_token_required
def payroll_nz_timesheets_nz_read_all():
    code = get_code_snippet("TIMESHEETS_NZ","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrollnz_api = PayrollNzApi(api_client)

    #[TIMESHEETS_NZ:READ_ALL]
    try:
        read_all_timesheets = payrollnz_api.get_timesheets(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Timesheets - total: {}".format(
            getvalue(read_all_timesheets, "pagination.item_count", "")
        )
        json = serialize_model(read_all_timesheets)
    #[/TIMESHEETS_NZ:READ_ALL]

    return render_template(
        "output.html", title="Timesheets", code=code, output=output, json=json, len = 0, set="payroll_nz", endpoint="timesheets_nz", action="read_all"
    )

@app.route("/payroll_nz_settings_nz_read_all")
@xero_token_required
def payroll_nz_settings_nz_read_all():
    code = get_code_snippet("SETTINGS_NZ","READ")

    xero_tenant_id = get_xero_tenant_id()
    payrollnz_api = PayrollNzApi(api_client)

    #[SETTINGS_NZ:READ]
    try:
        read_settings = payrollnz_api.get_settings(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Settings - first name: {}".format(
            getvalue(read_settings, "settings.accounts.0.name", "")
        )
        json = serialize_model(read_settings)
    #[/SETTINGS_NZ:READ]

    return render_template(
        "output.html", title="Settings", code=code, output=output, json=json, len = 0, set="payroll_nz", endpoint="settings_nz", action="read"
    )

@app.route("/payroll_nz_tracking_categories_nz_read_all")
@xero_token_required
def payroll_nz_tracking_categories_nz_read_all():
    code = get_code_snippet("TRACKING_CATEGORIES_NZ","READ")

    xero_tenant_id = get_xero_tenant_id()
    payrollnz_api = PayrollNzApi(api_client)

    #[TRACKING_CATEGORIES_NZ:READ]
    try:
        read_tracking_categories = payrollnz_api.get_tracking_categories(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "tracking categories - employee group id: {}".format(
            getvalue(read_tracking_categories, "tracking_categories.employee_groups_tracking_category_id", "")
        )
        json = serialize_model(read_tracking_categories)
    #[/TRACKING_CATEGORIES_NZ:READ]

    return render_template(
        "output.html", title="Tracking Categories", code=code, output=output, json=json, len = 0, set="payroll_nz", endpoint="tracking_categories_nz", action="read"
    )

# UK PAYROLL ------------------------------>
@app.route("/payroll_uk_employee_uk_read_all")
@xero_token_required
def payroll_uk_employee_uk_read_all():
    code = get_code_snippet("EMPLOYEE_UK","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrolluk_api = PayrollUkApi(api_client)
    accounting_api = AccountingApi(api_client)

    #[EMPLOYEE_UK:READ_ALL]
    try:
        read_employees = payrolluk_api.get_employees(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Employees read all - found: {}".format(read_employees.pagination.item_count)
        json = serialize_model(read_employees)
    #[/EMPLOYEE_UK:READ_ALL]

    return render_template(
        "output.html", title="Employees", code=code, output=output, json=json, len = 0, set="payroll_uk", endpoint="employee_uk", action="read_all"
    )

@app.route("/payroll_uk_employment_uk_create")
@xero_token_required
def payroll_uk_employment_uk_create():
    code = get_code_snippet("EMPLOYMENT_UK","CREATE")

    xero_tenant_id = get_xero_tenant_id()
    payrolluk_api = PayrollUkApi(api_client)
    accounting_api = AccountingApi(api_client)

    try:
        read_employees = payrolluk_api.get_employees(
            xero_tenant_id
        )
        employee_id = getvalue(read_employees, "employees.0.employee_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    try:
        read_pay_run_calendar = payrolluk_api.get_pay_run_calendars(
            xero_tenant_id
        )
        payroll_calendar_id = getvalue(read_pay_run_calendar, "pay_run_calendars.0.payroll_calendar_id", "")
        print(payroll_calendar_id)
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[EMPLOYMENT_UK:CREATE]
    employment = Employment(
        employee_number="12345",
        ni_category="A",
        start_date=dateutil.parser.parse("2020-08-01T00:00:00Z"),
        payroll_calendar_id=payroll_calendar_id
    )

    try:
        read_employment = payrolluk_api.create_employment(
            xero_tenant_id, employee_id=employee_id, employment=employment
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Employment created successfully"
        json = serialize_model(read_employment)
    #[/EMPLOYMENT_UK:CREATE]

    return render_template(
        "output.html", title="Employment", code=code, output=output, json=json, len = 0, set="payroll_uk", endpoint="employment_uk", action="create"
    )

@app.route("/payroll_uk_employee_tax_uk_read_all")
@xero_token_required
def payroll_uk_employee_tax_uk_read_all():
    code = get_code_snippet("EMPLOYEE_TAX_UK","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrolluk_api = PayrollUkApi(api_client)
    accounting_api = AccountingApi(api_client)

    #[EMPLOYEE_TAX_UK:READ_ALL]
    try:
        read_employees = payrolluk_api.get_employees(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Employees read all - found: {}".format(read_employees.pagination.item_count)
        json = serialize_model(read_employees)
    #[/EMPLOYEE_TAX_UK:READ_ALL]

    return render_template(
        "output.html", title="Employee Tax", code=code, output=output, json=json, len = 0, set="payroll_uk", endpoint="employee_tax_uk", action="read_all"
    )

@app.route("/payroll_uk_employee_opening_balance_uk_read_all")
@xero_token_required
def payroll_uk_employee_opening_balance_uk_read_all():
    code = get_code_snippet("EMPLOYEE_OPENING_BALANCE_UK","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrolluk_api = PayrollUkApi(api_client)
    accounting_api = AccountingApi(api_client)

    try:
        read_employees = payrolluk_api.get_employees(
            xero_tenant_id
        )
        employee_id = getvalue(read_employees, "employees.0.employee_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[EMPLOYEE_OPENING_BALANCE_UK:READ_ALL]
    try:
        read_employee_opening_balance = payrolluk_api.get_employee_opening_balances(
            xero_tenant_id, employee_id=employee_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Employee Opening Balance read all - prior employee number: {}".format(read_employee_opening_balance.opening_balances.prior_employee_number)
        json = serialize_model(read_employee_opening_balance)
    #[/EMPLOYEE_OPENING_BALANCE_UK:READ_ALL]

    return render_template(
        "output.html", title="Employee Opening Balance", code=code, output=output, json=json, len = 0, set="payroll_uk", endpoint="employee_opening_balance_uk", action="read_all"
    )

@app.route("/payroll_uk_employee_leaves_uk_read_all")
@xero_token_required
def payroll_uk_employee_leaves_uk_read_all():
    code = get_code_snippet("EMPLOYEE_LEAVES_UK","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrolluk_api = PayrollUkApi(api_client)
    accounting_api = AccountingApi(api_client)

    try:
        read_employees = payrolluk_api.get_employees(
            xero_tenant_id
        )
        employee_id = getvalue(read_employees, "employees.0.employee_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[EMPLOYEE_LEAVES_UK:READ_ALL]
    try:
        read_employee_leaves = payrolluk_api.get_employee_leaves(
            xero_tenant_id, employee_id=employee_id
        )
    except PayrollUkBadRequestException as exception:
        output = "Error: " + getvalue(exception.error_data, "problem.detail", "")
        json = jsonify(exception.error_data)
    else:
        output = "Employee Leave read all - found: {}".format( len(read_employee_leaves.leave) )
        json = serialize_model(read_employee_leaves)
    #[/EMPLOYEE_LEAVES_UK:READ_ALL]

    return render_template(
        "output.html", title="Employee Leave", code=code, output=output, json=json, len = 0, set="payroll_uk", endpoint="employee_leaves_uk", action="read_all"
    )

@app.route("/payroll_uk_employee_leave_balances_uk_read_all")
@xero_token_required
def payroll_uk_employee_leave_balances_uk_read_all():
    code = get_code_snippet("EMPLOYEE_LEAVE_BALANCES_UK","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrolluk_api = PayrollUkApi(api_client)
    accounting_api = AccountingApi(api_client)

    try:
        read_employees = payrolluk_api.get_employees(
            xero_tenant_id
        )
        employee_id = getvalue(read_employees, "employees.0.employee_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[EMPLOYEE_LEAVE_BALANCES_UK:READ_ALL]
    try:
        read_employee_leave_balances = payrolluk_api.get_employee_leave_balances(
            xero_tenant_id, employee_id=employee_id
        )
    except PayrollUkBadRequestException as exception:
        output = "Error: " + getvalue(exception.error_data, "problem.detail", "")
        json = jsonify(exception.error_data)
    else:
        output = "Employee Leave Balances read all - found: {}".format(read_employee_leave_balances.pagination.item_count)
        json = serialize_model(read_employee_leave_balances)
    #[/EMPLOYEE_LEAVE_BALANCES_UK:READ_ALL]

    return render_template(
        "output.html", title="Employee Leave", code=code, output=output, json=json, len = 0, set="payroll_uk", endpoint="employee_leave_balances_uk", action="read_all"
    )

@app.route("/payroll_uk_employee_statutory_leave_balance_uk_read_all")
@xero_token_required
def payroll_uk_employee_statutory_leave_balance_uk_read_all():
    code = get_code_snippet("EMPLOYEE_STATUTORYLEAVE_BALANCES_UK","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrolluk_api = PayrollUkApi(api_client)
    accounting_api = AccountingApi(api_client)

    try:
        read_employees = payrolluk_api.get_employees(
            xero_tenant_id
        )
        employee_id = getvalue(read_employees, "employees.0.employee_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[EMPLOYEE_STATUTORYLEAVE_BALANCES_UK:READ_ALL]
    as_of_date = dateutil.parser.parse("2020-07-25T00:00:00Z"),
    try:
        read_employee_statutory_leave_balances = payrolluk_api.get_employee_statutory_leave_balances(
            xero_tenant_id, employee_id=employee_id, leave_type="Sick", as_of_date=as_of_date
        )
    except PayrollUkBadRequestException as exception:
        output = "Error: " + getvalue(exception.error_data, "problem.detail", "")
        json = jsonify(exception.error_data)
    else:
        output = "Employee Statutory Leave Balances read balance remaining: {}".format(read_employee_statutory_leave_balances.leave_balance.balance_remaining)
        json = serialize_model(read_employee_statutory_leave_balances)
    #[/EMPLOYEE_STATUTORYLEAVE_BALANCES_UK:READ_ALL]

    return render_template(
        "output.html", title="Employee Leave", code=code, output=output, json=json, len = 0, set="payroll_uk", endpoint="employee_statutory_leave_balance_uk", action="read_all"
    )


@app.route("/payroll_uk_employee_statutory_leave_summary_uk_read_all")
@xero_token_required
def payroll_uk_employee_statutory_leave_summary_uk_read_all():
    code = get_code_snippet("EMPLOYEE_STATUTORY_LEAVE_SUMMARY_UK","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrolluk_api = PayrollUkApi(api_client)
    accounting_api = AccountingApi(api_client)

    try:
        read_employees = payrolluk_api.get_employees(
            xero_tenant_id
        )
        employee_id = getvalue(read_employees, "employees.0.employee_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)


    #[EMPLOYEE_STATUTORY_LEAVE_SUMMARY_UK:READ_ALL]
    try:
        read_statutory_leave_summary = payrolluk_api.get_statutory_leave_summary(
            xero_tenant_id, employee_id=employee_id
        )
    except PayrollUkBadRequestException as exception:
        output = "Error: " + getvalue(exception.error_data, "problem.detail", "")
        json = jsonify(exception.error_data)
    else:
        output = "Employee Statutory Leave Summary read all - found: {}".format( len(read_statutory_leave_summary.statutory_leaves) )
        json = serialize_model(read_statutory_leave_summary)
    #[/EMPLOYEE_STATUTORY_LEAVE_SUMMARY_UK:READ_ALL]

    return render_template(
        "output.html", title="Employee Leave", code=code, output=output, json=json, len = 0, set="payroll_uk", endpoint="employee_statutory_leave_summary_uk", action="read_all"
    )

@app.route("/payroll_uk_employee_statutory_sick_leave_uk_read_all")
@xero_token_required
def payroll_uk_employee_statutory_sick_leave_uk_read_all():
    code = get_code_snippet("EMPLOYEE_STATUTORY_SICK_LEAVE_UK","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrolluk_api = PayrollUkApi(api_client)
    accounting_api = AccountingApi(api_client)

    try:
        read_employees = payrolluk_api.get_employees(
            xero_tenant_id
        )
        employee_id = getvalue(read_employees, "employees.0.employee_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    try:
        read_statutory_leave_summary = payrolluk_api.get_statutory_leave_summary(
            xero_tenant_id, employee_id=employee_id
        )
        statutory_sick_leave_id = getvalue(read_statutory_leave_summary, "statutory_leaves.0.statutory_leave_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[EMPLOYEE_STATUTORY_SICK_LEAVE_UK:READ_ALL]
    try:
        read_employee_statutory_sick_leave = payrolluk_api.get_employee_statutory_sick_leave(
            xero_tenant_id, statutory_sick_leave_id=statutory_sick_leave_id
        )
    except PayrollUkBadRequestException as exception:
        output = "Error: " + getvalue(exception.error_data, "problem.detail", "")
        json = jsonify(exception.error_data)
    else:
        output = "Employee Statutory Sick Leave date: {}".format(read_employee_statutory_sick_leave.statutory_sick_leave.start_date)
        json = serialize_model(read_employee_statutory_sick_leave)
    #[/EMPLOYEE_STATUTORY_SICK_LEAVE_UK:READ_ALL]

    return render_template(
        "output.html", title="Employee Statutory Sick Leave", code=code, output=output, json=json, len = 0, set="payroll_uk", endpoint="employee_statutory_sick_leave_uk", action="read_all"
    )

@app.route("/payroll_uk_employee_leave_periods_uk_read_all")
@xero_token_required
def payroll_uk_employee_leave_periods_uk_read_all():
    code = get_code_snippet("EMPLOYEE_LEAVE_PERIODS_UK","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrolluk_api = PayrollUkApi(api_client)
    accounting_api = AccountingApi(api_client)

    try:
        read_employees = payrolluk_api.get_employees(
            xero_tenant_id
        )
        employee_id = getvalue(read_employees, "employees.0.employee_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[EMPLOYEE_LEAVE_PERIODS_UK:READ_ALL]
    start_date= dateutil.parser.parse("2020-07-01T00:00:00Z")
    end_date= dateutil.parser.parse("2020-08-01T00:00:00Z")
    try:
        read_employee_leave_periods = payrolluk_api.get_employee_leave_periods(
            xero_tenant_id, employee_id=employee_id, start_date=start_date, end_date=end_date
        )
    except PayrollUkBadRequestException as exception:
        output = "Error: " + getvalue(exception.error_data, "problem.detail", "")
        json = jsonify(exception.error_data)
    else:
        output = "Employee Leave Periods read all - found: {}".format( len(read_employee_leave_periods.periods) )
        json = serialize_model(read_employee_leave_periods)
    #[/EMPLOYEE_LEAVE_PERIODS_UK:READ_ALL]

    return render_template(
        "output.html", title="Employee Leave Periods", code=code, output=output, json=json, len = 0, set="payroll_uk", endpoint="employee_leave_periods_uk", action="read_all"
    )

@app.route("/payroll_uk_employee_leave_types_uk_read_all")
@xero_token_required
def payroll_uk_employee_leave_types_uk_read_all():
    code = get_code_snippet("EMPLOYEE_LEAVE_TYPES_UK","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrolluk_api = PayrollUkApi(api_client)
    accounting_api = AccountingApi(api_client)

    try:
        read_employees = payrolluk_api.get_employees(
            xero_tenant_id
        )
        employee_id = getvalue(read_employees, "employees.0.employee_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[EMPLOYEE_LEAVE_TYPES_UK:READ_ALL]
    try:
        read_employee_leave_types = payrolluk_api.get_employee_leave_types(
            xero_tenant_id, employee_id=employee_id
        )
    except PayrollUkBadRequestException as exception:
        output = "Error: " + getvalue(exception.error_data, "problem.detail", "")
        json = jsonify(exception.error_data)
    else:
        output = "Employee Leave Types read all - found: {}".format( len(read_employee_leave_types.leave_types) )
        json = serialize_model(read_employee_leave_types)
    #[/EMPLOYEE_LEAVE_TYPES_UK:READ_ALL]

    return render_template(
        "output.html", title="Employee Leave Types", code=code, output=output, json=json, len = 0, set="payroll_uk", endpoint="employee_leave_types_uk", action="read_all"
    )

@app.route("/payroll_uk_employee_pay_template_uk_read_all")
@xero_token_required
def payroll_uk_employee_pay_template_uk_read_all():
    code = get_code_snippet("EMPLOYEE_PAY_TEMPLATE_UK","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrolluk_api = PayrollUkApi(api_client)
    accounting_api = AccountingApi(api_client)

    try:
        read_employees = payrolluk_api.get_employees(
            xero_tenant_id
        )
        employee_id = getvalue(read_employees, "employees.0.employee_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[EMPLOYEE_PAY_TEMPLATE_UK:READ_ALL]
    try:
        read_employee_pay_template = payrolluk_api.get_employee_pay_template(
            xero_tenant_id, employee_id=employee_id
        )
    except PayrollUkBadRequestException as exception:
        output = "Error: " + getvalue(exception.error_data, "problem.detail", "")
        json = jsonify(exception.error_data)
    else:
        output = "Employee Pay Template with Earning templates read all - found: {}".format( len(read_employee_pay_template.pay_template.earning_templates) )
        json = serialize_model(read_employee_pay_template)
    #[/EMPLOYEE_PAY_TEMPLATE_UK:READ_ALL]

    return render_template(
        "output.html", title="Employee Pay Template", code=code, output=output, json=json, len = 0, set="payroll_uk", endpoint="employee_pay_template_uk", action="read_all"
    )

@app.route("/payroll_uk_employer_pensions_uk_read_all")
@xero_token_required
def payroll_uk_employer_pensions_uk_read_all():
    code = get_code_snippet("EMPLOYER_PENSIONS_UK","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrolluk_api = PayrollUkApi(api_client)
    accounting_api = AccountingApi(api_client)

    #[EMPLOYER_PENSIONS_UK:READ_ALL]
    try:
        read_employer_pensions = payrolluk_api.get_benefits(
            xero_tenant_id
        )
    except PayrollUkBadRequestException as exception:
        output = "Error: " + getvalue(exception.error_data, "problem.detail", "")
        json = jsonify(exception.error_data)
    else:
        output = "Employer Pensions (aka Benefits) read all - found: {}".format( read_employer_pensions.pagination.item_count )
        json = serialize_model(read_employer_pensions)
    #[/EMPLOYER_PENSIONS_UK:READ_ALL]

    return render_template(
        "output.html", title="Employer Pensions", code=code, output=output, json=json, len = 0, set="payroll_uk", endpoint="employer_pensions_uk", action="read_all"
    )

@app.route("/payroll_uk_deductions_uk_read_all")
@xero_token_required
def payroll_uk_deductions_uk_read_all():
    code = get_code_snippet("DEDUCTIONS_UK","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrolluk_api = PayrollUkApi(api_client)
    accounting_api = AccountingApi(api_client)

    #[DEDUCTIONS_UK:READ_ALL]
    try:
        read_deductions = payrolluk_api.get_deductions(
            xero_tenant_id
        )
    except PayrollUkBadRequestException as exception:
        output = "Error: " + getvalue(exception.error_data, "problem.detail", "")
        json = jsonify(exception.error_data)
    else:
        output = "Deductions read all - found: {}".format( read_deductions.pagination.item_count )
        json = serialize_model(read_deductions)
    #[/DEDUCTIONS_UK:READ_ALL]

    return render_template(
        "output.html", title="Deductions", code=code, output=output, json=json, len = 0, set="payroll_uk", endpoint="deductions_uk", action="read_all"
    )

@app.route("/payroll_uk_earnings_orders_uk_read_all")
@xero_token_required
def payroll_uk_earnings_orders_uk_read_all():
    code = get_code_snippet("EARNINGS_ORDERS_UK","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrolluk_api = PayrollUkApi(api_client)
    accounting_api = AccountingApi(api_client)

    #[EARNINGS_ORDERS_UK:READ_ALL]
    try:
        read_earnings_orders = payrolluk_api.get_earnings_orders(
            xero_tenant_id
        )
    except PayrollUkBadRequestException as exception:
        output = "Error: " + getvalue(exception.error_data, "problem.detail", "")
        json = jsonify(exception.error_data)
    else:
        output = "Earnings Orders read all - found: {}".format( read_earnings_orders.pagination.item_count )
        json = serialize_model(read_earnings_orders)
    #[/EARNINGS_ORDERS_UK:READ_ALL]

    return render_template(
        "output.html", title="Earnings Orders", code=code, output=output, json=json, len = 0, set="payroll_uk", endpoint="earnings_orders_uk", action="read_all"
    )

@app.route("/payroll_uk_earnings_rates_uk_read_all")
@xero_token_required
def payroll_uk_earnings_rates_uk_read_all():
    code = get_code_snippet("EARNINGS_RATES_UK","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrolluk_api = PayrollUkApi(api_client)
    accounting_api = AccountingApi(api_client)

    #[EARNINGS_RATES_UK:READ_ALL]
    try:
        read_earnings_rates = payrolluk_api.get_earnings_rates(
            xero_tenant_id
        )
    except PayrollUkBadRequestException as exception:
        output = "Error: " + getvalue(exception.error_data, "problem.detail", "")
        json = jsonify(exception.error_data)
    else:
        output = "Earnings Rates read all - found: {}".format( read_earnings_rates.pagination.item_count )
        json = serialize_model(read_earnings_rates)
    #[/EARNINGS_RATES_UK:READ_ALL]

    return render_template(
        "output.html", title="Earnings Rates", code=code, output=output, json=json, len = 0, set="payroll_uk", endpoint="earnings_rates_uk", action="read_all"
    )

@app.route("/payroll_uk_leave_types_uk_read_all")
@xero_token_required
def payroll_uk_leave_types_uk_read_all():
    code = get_code_snippet("LEAVE_TYPES_UK","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrolluk_api = PayrollUkApi(api_client)
    accounting_api = AccountingApi(api_client)

    #[LEAVE_TYPES_UK:READ_ALL]
    try:
        read_leave_types = payrolluk_api.get_leave_types(
            xero_tenant_id
        )
    except PayrollUkBadRequestException as exception:
        output = "Error: " + getvalue(exception.error_data, "problem.detail", "")
        json = jsonify(exception.error_data)
    else:
        output = "Leave Types read all - found: {}".format( read_leave_types.pagination.item_count )
        json = serialize_model(read_leave_types)
    #[/LEAVE_TYPES_UK:READ_ALL]

    return render_template(
        "output.html", title="Leave Types", code=code, output=output, json=json, len = 0, set="payroll_uk", endpoint="leave_types_uk", action="read_all"
    )

@app.route("/payroll_uk_reimbursements_uk_read_all")
@xero_token_required
def payroll_uk_reimbursements_uk_read_all():
    code = get_code_snippet("REIMBURSEMENTS_UK","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrolluk_api = PayrollUkApi(api_client)
    accounting_api = AccountingApi(api_client)

    #[REIMBURSEMENTS_UK:READ_ALL]
    try:
        read_reimbursements = payrolluk_api.get_reimbursements(
            xero_tenant_id
        )
    except PayrollUkBadRequestException as exception:
        output = "Error: " + getvalue(exception.error_data, "problem.detail", "")
        json = jsonify(exception.error_data)
    else:
        output = "Reimbursements read all - found: {}".format( read_reimbursements.pagination.item_count )
        json = serialize_model(read_reimbursements)
    #[/REIMBURSEMENTS_UK:READ_ALL]

    return render_template(
        "output.html", title="Reimbursements", code=code, output=output, json=json, len = 0, set="payroll_uk", endpoint="reimbursements_uk", action="read_all"
    )

@app.route("/payroll_uk_timesheets_uk_read_all")
@xero_token_required
def payroll_uk_timesheets_uk_read_all():
    code = get_code_snippet("TIMESHEETS_UK","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrolluk_api = PayrollUkApi(api_client)
    accounting_api = AccountingApi(api_client)

    #[TIMESHEETS_UK:READ_ALL]
    try:
        read_timesheets = payrolluk_api.get_timesheets(
            xero_tenant_id
        )
    except PayrollUkBadRequestException as exception:
        output = "Error: " + getvalue(exception.error_data, "problem.detail", "")
        json = jsonify(exception.error_data)
    else:
        output = "Timesheets read all - found: {}".format( read_timesheets.pagination.item_count )
        json = serialize_model(read_timesheets)
    #[/TIMESHEETS_UK:READ_ALL]

    return render_template(
        "output.html", title="Timesheets", code=code, output=output, json=json, len = 0, set="payroll_uk", endpoint="timesheets_uk", action="read_all"
    )

@app.route("/payroll_uk_payment_methods_uk_read_all")
@xero_token_required
def payroll_uk_payment_methods_uk_read_all():
    code = get_code_snippet("PAYMENT_METHODS_UK","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrolluk_api = PayrollUkApi(api_client)
    accounting_api = AccountingApi(api_client)

    try:
        read_employees = payrolluk_api.get_employees(
            xero_tenant_id
        )
        employee_id = getvalue(read_employees, "employees.0.employee_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[PAYMENT_METHODS_UK:READ_ALL]
    try:
        read_payment_methods = payrolluk_api.get_employee_payment_method(
            xero_tenant_id, employee_id=employee_id
        )
    except PayrollUkBadRequestException as exception:
        output = "Error: " + getvalue(exception.error_data, "problem.detail", "")
        json = jsonify(exception.error_data)
    else:
        output = "Payment Methods read all bank accounts - found: {}".format( len(read_payment_methods.payment_method.bank_accounts) )
        json = serialize_model(read_payment_methods)
    #[/PAYMENT_METHODS_UK:READ_ALL]

    return render_template(
        "output.html", title="Payment Methods", code=code, output=output, json=json, len = 0, set="payroll_uk", endpoint="payment_methods_uk", action="read_all"
    )

@app.route("/payroll_uk_pay_run_calendars_uk_read_all")
@xero_token_required
def payroll_uk_pay_run_calendars_uk_read_all():
    code = get_code_snippet("PAY_RUN_CALENDARS_UK","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrolluk_api = PayrollUkApi(api_client)
    accounting_api = AccountingApi(api_client)

    try:
        read_employees = payrolluk_api.get_employees(
            xero_tenant_id
        )
        employee_id = getvalue(read_employees, "employees.0.employee_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[PAY_RUN_CALENDARS_UK:READ_ALL]
    try:
        read_pay_run_calendars = payrolluk_api.get_pay_run_calendars(
            xero_tenant_id
        )
    except PayrollUkBadRequestException as exception:
        output = "Error: " + getvalue(exception.error_data, "problem.detail", "")
        json = jsonify(exception.error_data)
    else:
        output = "Pay Run Calendars read all bank accounts - found: {}".format( read_pay_run_calendars.pagination.item_count )
        json = serialize_model(read_pay_run_calendars)
    #[/PAY_RUN_CALENDARS_UK:READ_ALL]

    return render_template(
        "output.html", title="Pay Run Calendars", code=code, output=output, json=json, len = 0, set="payroll_uk", endpoint="pay_run_calendars_uk", action="read_all"
    )

@app.route("/payroll_uk_salary_and_wage_uk_read_all")
@xero_token_required
def payroll_uk_salary_and_wage_uk_read_all():
    code = get_code_snippet("SALARY_AND_WAGE_UK","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrolluk_api = PayrollUkApi(api_client)
    accounting_api = AccountingApi(api_client)

    try:
        read_employees = payrolluk_api.get_employees(
            xero_tenant_id
        )
        employee_id = getvalue(read_employees, "employees.0.employee_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[SALARY_AND_WAGE_UK:READ_ALL]
    try:
        read_salary_and_wage = payrolluk_api.get_employee_salary_and_wages(
            xero_tenant_id, employee_id=employee_id
        )
    except PayrollUkBadRequestException as exception:
        output = "Error: " + getvalue(exception.error_data, "problem.detail", "")
        json = jsonify(exception.error_data)
    else:
        output = "Salary and Wage read all bank accounts - found: {}".format( read_salary_and_wage.pagination.item_count )
        json = serialize_model(read_salary_and_wage)
    #[/SALARY_AND_WAGE_UK:READ_ALL]

    return render_template(
        "output.html", title="Salary and Wage", code=code, output=output, json=json, len = 0, set="payroll_uk", endpoint="salary_and_wage_uk", action="read_all"
    )

@app.route("/payroll_uk_pay_runs_uk_read_all")
@xero_token_required
def payroll_uk_pay_runs_uk_read_all():
    code = get_code_snippet("PAY_RUNS_UK","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrolluk_api = PayrollUkApi(api_client)
    accounting_api = AccountingApi(api_client)

    #[PAY_RUNS_UK:READ_ALL]
    try:
        read_pay_runs = payrolluk_api.get_pay_runs(
            xero_tenant_id
        )
    except PayrollUkBadRequestException as exception:
        output = "Error: " + getvalue(exception.error_data, "problem.detail", "")
        json = jsonify(exception.error_data)
    else:
        output = "Pay runs read all bank accounts - found: {}".format( read_pay_runs.pagination.item_count )
        json = serialize_model(read_pay_runs)
    #[/PAY_RUNS_UK:READ_ALL]

    return render_template(
        "output.html", title="Pay runs", code=code, output=output, json=json, len = 0, set="payroll_uk", endpoint="pay_runs_uk", action="read_all"
    )

@app.route("/payroll_uk_pay_slips_uk_read_all")
@xero_token_required
def payroll_uk_pay_slips_uk_read_all():
    code = get_code_snippet("PAY_SLIPS_UK","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrolluk_api = PayrollUkApi(api_client)
    accounting_api = AccountingApi(api_client)

    try:
        read_pay_runs = payrolluk_api.get_pay_runs(
            xero_tenant_id
        )
        pay_run_id = getvalue(read_pay_runs, "pay_runs.0.pay_run_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[PAY_SLIPS_UK:READ_ALL]
    try:
        read_pay_slips = payrolluk_api.get_pay_slips(
            xero_tenant_id, pay_run_id=pay_run_id
        )
    except PayrollUkBadRequestException as exception:
        output = "Error: " + getvalue(exception.error_data, "problem.detail", "")
        json = jsonify(exception.error_data)
    else:
        output = "Pay slips read all bank accounts - found: {}".format( read_pay_slips.pagination.item_count )
        json = serialize_model(read_pay_slips)
    #[/PAY_SLIPS_UK:READ_ALL]

    return render_template(
        "output.html", title="Pay slips", code=code, output=output, json=json, len = 0, set="payroll_uk", endpoint="pay_slips_uk", action="read_all"
    )

@app.route("/payroll_uk_settings_uk_read_all")
@xero_token_required
def payroll_uk_settings_uk_read_all():
    code = get_code_snippet("SETTINGS_UK","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrolluk_api = PayrollUkApi(api_client)
    accounting_api = AccountingApi(api_client)

    #[SETTINGS_UK:READ_ALL]
    try:
        read_settings = payrolluk_api.get_settings(
            xero_tenant_id
        )
    except PayrollUkBadRequestException as exception:
        output = "Error: " + getvalue(exception.error_data, "problem.detail", "")
        json = jsonify(exception.error_data)
    else:
        output = "Settings read all bank accounts - found: {}".format( len(read_settings.settings.accounts) )
        json = serialize_model(read_settings)
    #[/SETTINGS_UK:READ_ALL]

    return render_template(
        "output.html", title="Settings", code=code, output=output, json=json, len = 0, set="payroll_uk", endpoint="settings_uk", action="read_all"
    )

@app.route("/payroll_uk_tracking_categories_uk_read_all")
@xero_token_required
def payroll_uk_tracking_categories_uk_read_all():
    code = get_code_snippet("TRACKING_CATEGORIES_UK","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    payrolluk_api = PayrollUkApi(api_client)
    accounting_api = AccountingApi(api_client)

    #[TRACKING_CATEGORIES_UK:READ_ALL]
    try:
        read_tracking_categories = payrolluk_api.get_tracking_categories(
            xero_tenant_id
        )
    except PayrollUkBadRequestException as exception:
        output = "Error: " + getvalue(exception.error_data, "problem.detail", "")
        json = jsonify(exception.error_data)
    else:
        output = "Tracking categories read all"
        json = serialize_model(read_tracking_categories)
    #[/TRACKING_CATEGORIES_UK:READ_ALL]

    return render_template(
        "output.html", title="Tracking categories", code=code, output=output, json=json, len = 0, set="payroll_uk", endpoint="tracking_categories_uk", action="read_all"
    )

@app.route("/files_file_read_all")
@xero_token_required
def files_file_read_all():
    code = get_code_snippet("FILE","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    files_api = FilesApi(api_client)
    accounting_api = AccountingApi(api_client)

    #[FILE:READ_ALL]
    try:
        read_files = files_api.get_files(
            xero_tenant_id, 
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "File Read (all)"
        json = serialize_model(read_files)
    #[/FILE:READ_ALL]

    return render_template(
        "output.html", title="File Read (all)", code=code, output=output, json=json, len = 0, set="files", endpoint="file", action="read_all"
    )

@app.route("/files_file_read_one")
@xero_token_required
def files_file_read_one():
    code = get_code_snippet("FILE","READ_ONE")

    xero_tenant_id = get_xero_tenant_id()
    files_api = FilesApi(api_client)
    accounting_api = AccountingApi(api_client)
    
    try:
        read_files = files_api.get_files(
            xero_tenant_id, 
        )
        file_id = getvalue(read_files, "items.0.id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    
    #[FILE:READ_ONE]
    try:
        read_file = files_api.get_file(
            xero_tenant_id, file_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "File Read (one)"
        json = serialize_model(read_file)
    #[/FILE:READ_ONE]

    return render_template(
        "output.html", title="File Read (one)", code=code, output=output, json=json, len = 0, set="files", endpoint="file", action="read_one"
    )

@app.route("/files_file_upload")
@xero_token_required
def files_file_upload():
    code = get_code_snippet("FILE","UPLOAD")

    xero_tenant_id = get_xero_tenant_id()
    files_api = FilesApi(api_client)
    accounting_api = AccountingApi(api_client)

    #[FILE:UPLOAD]
    name = "helo-heros"
    filename= "helo-heros.jpg"
    mime_type = "image/jpg"
    with open('helo-heros.jpg', 'rb') as f:
        body = f.read()

    try:
        file_object = files_api.upload_file(
            xero_tenant_id, 
            name = name, 
            filename= filename, 
            mime_type = mime_type,
            body=body
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "File upload"
        json = serialize_model(file_object)
    #[/FILE:UPLOAD]

    return render_template(
        "output.html", title="File upload", code=code, output=output, json=json, len = 0, set="files", endpoint="file", action="upload"
    )

@app.route("/files_folder_read_all")
@xero_token_required
def files_folder_read_all():
    code = get_code_snippet("FOLDER","READ_ALL")

    xero_tenant_id = get_xero_tenant_id()
    files_api = FilesApi(api_client)
    accounting_api = AccountingApi(api_client)

    #[FOLDER:READ_ALL]
    try:
        folders = files_api.get_folders(
            xero_tenant_id, 
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Folder Read (all)"
        json = serialize_model(folders)
    #[/FOLDER:READ_ALL]

    return render_template(
        "output.html", title="Folder Read (all)", code=code, output=output, json=json, len = 0, set="files", endpoint="folder", action="read_all"
    )

@app.route("/files_folder_read_one")
@xero_token_required
def files_folder_read_one():
    code = get_code_snippet("FOLDER","READ_ONE")

    xero_tenant_id = get_xero_tenant_id()
    files_api = FilesApi(api_client)
    accounting_api = AccountingApi(api_client)

    try:
        read_folders = files_api.get_folders(
            xero_tenant_id, 
        )
        folder_id = getvalue(read_folders, "1.id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
        
    #[FOLDER:READ_ONE]
    try:
        read_folder = files_api.get_folder(
            xero_tenant_id, folder_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Folder Read (one)"
        json = serialize_model(read_folder)
    #[/FOLDER:READ_ONE]

    return render_template(
        "output.html", title="Folder Read (one)", code=code, output=output, json=json, len = 0, set="files", endpoint="folder", action="read_one"
    )

@app.route("/files_folder_read_inbox")
@xero_token_required
def files_folder_read_inbox():
    code = get_code_snippet("FOLDER","READ_INBOX")

    xero_tenant_id = get_xero_tenant_id()
    files_api = FilesApi(api_client)
    accounting_api = AccountingApi(api_client)

    #[FOLDER:READ_INBOX]
    try:
        read_inbox = files_api.get_inbox(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Inbox Read"
        json = serialize_model(read_inbox)
    #[/FOLDER:READ_INBOX]

    return render_template(
        "output.html", title="Inbox Read", code=code, output=output, json=json, len = 0, set="files", endpoint="folder", action="read_inbox"
    )

@app.route("/finance_accounting_activities_account_usage_read_all")
@xero_token_required
def finance_accounting_activities_account_usage_read_all():
    code = get_code_snippet("ACCOUNTINGACTIVITYACCOUNTUSAGE","READ_ALL")

    #[ACCOUNTINGACTIVITYACCOUNTUSAGE:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    finance_api = FinanceApi(api_client)

    try:
        read_accounting_activity_account_usage = finance_api.get_accounting_activity_account_usage(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Accounting activity account usage for org ID {} ".format(
            getvalue(read_accounting_activity_account_usage, "organisation_id", "")
        )
        json = serialize_model(read_accounting_activity_account_usage)
    #[/ACCOUNTINGACTIVITYACCOUNTUSAGE:READ_ALL]

    return render_template(
        "output.html", title="Accounting Activity Account Usage", code=code, json=json, output=output, len = 0, set="finance", endpoint="accounting_activities", action="account_usage_read_all"
    )

@app.route("/finance_accounting_activities_lock_history_read_all")
@xero_token_required
def finance_accounting_activities_lock_history_read_all():
    code = get_code_snippet("ACCOUNTINGACTIVITYLOCKHISTORY","READ_ALL")

    #[ACCOUNTINGACTIVITYLOCKHISTORY:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    finance_api = FinanceApi(api_client)

    try:
        read_accounting_activity_lock_history = finance_api.get_accounting_activity_lock_history(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Accounting activity lock history for org ID {} ".format(
            getvalue(read_accounting_activity_lock_history, "organisation_id", "")
        )
        json = serialize_model(read_accounting_activity_lock_history)
    #[/ACCOUNTINGACTIVITYLOCKHISTORY:READ_ALL]

    return render_template(
        "output.html", title="Accounting Activity Lock History", code=code, json=json, output=output, len = 0, set="finance", endpoint="accounting_activities", action="lock_history_read_all"
    )

@app.route("/finance_accounting_activities_report_history_read_all")
@xero_token_required
def finance_accounting_activities_report_history_read_all():
    code = get_code_snippet("ACCOUNTINGACTIVITYREPORTHISTORY","READ_ALL")

    #[ACCOUNTINGACTIVITYREPORTHISTORY:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    finance_api = FinanceApi(api_client)

    try:
        read_accounting_activity_report_history = finance_api.get_accounting_activity_report_history(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Accounting activity report history for org ID {} ".format(
            getvalue(read_accounting_activity_report_history, "organisation_id", "")
        )
        json = serialize_model(read_accounting_activity_report_history)
    #[/ACCOUNTINGACTIVITYREPORTHISTORY:READ_ALL]

    return render_template(
        "output.html", title="Accounting Activity Report History", code=code, json=json, output=output, len = 0, set="finance", endpoint="accounting_activities", action="report_history_read_all"
    )

@app.route("/finance_accounting_activities_user_activities_read_all")
@xero_token_required
def finance_accounting_activities_user_activities_read_all():
    code = get_code_snippet("ACCOUNTINGACTIVITYUSERACTIVITIES","READ_ALL")

    #[ACCOUNTINGACTIVITYUSERACTIVITIES:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    finance_api = FinanceApi(api_client)

    try:
        read_accounting_activity_user_activities = finance_api.get_accounting_activity_user_activities(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Accounting activity user activities for org ID {} ".format(
            getvalue(read_accounting_activity_user_activities, "organisation_id", "")
        )
        json = serialize_model(read_accounting_activity_user_activities)
    #[/ACCOUNTINGACTIVITYUSERACTIVITIES:READ_ALL]

    return render_template(
        "output.html", title="Accounting Activity User Activities", code=code, json=json, output=output, len = 0, set="finance", endpoint="accounting_activities", action="user_activities_read_all"
    )

@app.route("/finance_cash_validation_read_all")
@xero_token_required
def finance_cash_validation_read_all():
    code = get_code_snippet("CASHVALIDATION","READ_ALL")

    #[CASHVALIDATION:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    finance_api = FinanceApi(api_client)

    try:
        read_cash_validation = finance_api.get_cash_validation(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Cash validation found for {} accounts".format( len(read_cash_validation) )
        json = serialize_model(read_cash_validation)
    #[/CASHVALIDATION:READ_ALL]

    return render_template(
        "output.html", title="Cash Validation", code=code, json=json, output=output, len = 0, set="finance", endpoint="cash_validation", action="read_all"
    )

@app.route("/finance_financial_statements_balance_sheet_read_all")
@xero_token_required
def finance_financial_statements_balance_sheet_read_all():
    code = get_code_snippet("BALANCESHEET","READ_ALL")

    #[BALANCESHEET:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    finance_api = FinanceApi(api_client)

    try:
        read_financial_statement_balance_sheet = finance_api.get_financial_statement_balance_sheet(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Balance sheet as of {} ".format(
            getvalue(read_financial_statement_balance_sheet, "balance_date", "")
        )
        json = serialize_model(read_financial_statement_balance_sheet)
    #[/BALANCESHEET:READ_ALL]

    return render_template(
        "output.html", title="Financial Statements Balance Sheet", code=code, json=json, output=output, len = 0, set="finance", endpoint="financial_statements", action="balance_sheet_read_all"
    )

@app.route("/finance_financial_statements_cashflow_read_all")
@xero_token_required
def finance_financial_statements_cashflow_read_all():
    code = get_code_snippet("CASHFLOW","READ_ALL")

    #[CASHFLOW:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    finance_api = FinanceApi(api_client)

    try:
        read_financial_statement_cashflow = finance_api.get_financial_statement_cashflow(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Cash flow ending {} ".format(
            getvalue(read_financial_statement_cashflow, "end_date", "")
        )
        json = serialize_model(read_financial_statement_cashflow)
    #[/CASHFLOW:READ_ALL]

    return render_template(
        "output.html", title="Financial Statements Cash Flow", code=code, json=json, output=output, len = 0, set="finance", endpoint="financial_statements", action="cashflow_read_all"
    )

@app.route("/finance_financial_statements_contacts_expense_read_all")
@xero_token_required
def finance_financial_statements_contacts_expense_read_all():
    code = get_code_snippet("CONTACTSEXPENSE","READ_ALL")

    #[CONTACTSEXPENSE:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    finance_api = FinanceApi(api_client)

    try:
        read_financial_statement_contacts_expense = finance_api.get_financial_statement_contacts_expense(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Contact expenses total of {} ".format(
            getvalue(read_financial_statement_contacts_expense, "total", "")
        )
        json = serialize_model(read_financial_statement_contacts_expense)
    #[/CONTACTSEXPENSE:READ_ALL]

    return render_template(
        "output.html", title="Financial Statements Contacts Expense", code=code, json=json, output=output, len = 0, set="finance", endpoint="financial_statements", action="contacts_expense_read_all"
    )

@app.route("/finance_financial_statements_contacts_revenue_read_all")
@xero_token_required
def finance_financial_statements_contacts_revenue_read_all():
    code = get_code_snippet("CONTACTSREVENUE","READ_ALL")

    #[CONTACTSREVENUE:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    finance_api = FinanceApi(api_client)

    try:
        read_financial_statement_contacts_revenue = finance_api.get_financial_statement_contacts_revenue(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Contact revenues total of {} ".format(
            getvalue(read_financial_statement_contacts_revenue, "total", "")
        )
        json = serialize_model(read_financial_statement_contacts_revenue)
    #[/CONTACTSREVENUE:READ_ALL]

    return render_template(
        "output.html", title="Financial Statements Contacts Revenue", code=code, json=json, output=output, len = 0, set="finance", endpoint="financial_statements", action="contacts_revenue_read_all"
    )

@app.route("/finance_financial_statements_profit_and_loss_read_all")
@xero_token_required
def finance_financial_statements_profit_and_loss_read_all():
    code = get_code_snippet("PROFITANDLOSS","READ_ALL")

    #[PROFITANDLOSS:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    finance_api = FinanceApi(api_client)

    try:
        read_financial_statement_profit_and_loss = finance_api.get_financial_statement_profit_and_loss(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Net profit and loss of {} ".format(
            getvalue(read_financial_statement_profit_and_loss, "net_profit_loss", "")
        )
        json = serialize_model(read_financial_statement_profit_and_loss)
    #[/PROFITANDLOSS:READ_ALL]

    return render_template(
        "output.html", title="Financial Statements Profit and Loss", code=code, json=json, output=output, len = 0, set="finance", endpoint="financial_statements", action="profit_and_loss_read_all"
    )

@app.route("/finance_financial_statements_trial_balance_read_all")
@xero_token_required
def finance_financial_statements_trial_balance_read_all():
    code = get_code_snippet("TRIALBALANCE","READ_ALL")

    #[TRIALBALANCE:READ_ALL]
    xero_tenant_id = get_xero_tenant_id()
    finance_api = FinanceApi(api_client)

    try:
        read_financial_statement_trial_balance = finance_api.get_financial_statement_trial_balance(
            xero_tenant_id
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Trial balance for {} accounts".format( len(read_financial_statement_trial_balance.accounts) )
        json = serialize_model(read_financial_statement_trial_balance)
    #[/TRIALBALANCE:READ_ALL]

    return render_template(
        "output.html", title="Financial Statements Trial Balance", code=code, json=json, output=output, len = 0, set="finance", endpoint="financial_statements", action="trial_balance_read_all"
    )

@app.route("/finance_bank_statement_accounting_read")
@xero_token_required
def finance_bank_statement_accounting_read():
    code = get_code_snippet("BANKSTATEMENTSPLUS","READ")
    xero_tenant_id = get_xero_tenant_id()
    accounting_api = AccountingApi(api_client)

    where = "Status==\"ACTIVE\" AND Type==\"BANK\""
    try:
        read_accounts_for_valid_status = accounting_api.get_accounts(
            xero_tenant_id, where=where
        )
        account_id = getvalue(read_accounts_for_valid_status, "accounts.0.account_id", "")
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)

    #[BANKSTATEMENTSPLUS:READ]
    xero_tenant_id = get_xero_tenant_id()
    finance_api = FinanceApi(api_client)

    try:
        read_bank_statements_plus = finance_api.get_bank_statement_accounting(
            xero_tenant_id, account_id, from_date="2021-04-01", to_date="2022-03-01"
        )
    except AccountingBadRequestException as exception:
        output = "Error: " + exception.reason
        json = jsonify(exception.error_data)
    else:
        output = "Bank Statement Data for Account ID: {}".format(account_id)
        json = serialize_model(read_bank_statements_plus)
    #[/BANKSTATEMENTSPLUS:READ]

    return render_template(
        "output.html", title="Bank Statement Accounting", code=code, json=json, output=output, len = 0, set="finance", endpoint="financial_statements", action="bank_statements_plus_read"
    )

@app.route("/login")
def login():
    redirect_url = url_for("oauth_callback", _external=True)
    session["state"] = app.config["STATE"]
    response = xero.authorize(callback_uri=redirect_url, state=session["state"])
    return response


@app.route("/callback")
def oauth_callback():
    if request.args.get("state") != session["state"]:
        return "Error, state doesn't match, no token for you."
    try:
        response = xero.authorized_response()
    except Exception as e:
        print(e)
        raise
    if response is None or response.get("access_token") is None:
        return "Access denied: response=%s" % response
    store_xero_oauth2_token(response)
    return redirect(url_for("index", _external=True))


@app.route("/disconnect")
def disconnect():
    connection_id = get_connection_id()
    identity_api = IdentityApi(api_client)
    identity_api.delete_connection(
        id=connection_id
    )

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
        "output.html",
        title="Xero OAuth2 token",
        code=jsonify({"Old Token": xero_token, "New token": new_token}),
        sub_title="token refreshed",
    )
@app.route("/revoke-token")
@xero_token_required
def revoke_token():
    xero_token = obtain_xero_oauth2_token()
    new_token = api_client.revoke_oauth2_token()
    session.pop('token', None)
    return render_template(
        "output.html",
        title="Xero OAuth2 token",
        code=jsonify({"Old Token": xero_token, "New token": new_token}),
        sub_title="token revoked",
    )


def get_connection_id():
    identity_api = IdentityApi(api_client)
    for connection in identity_api.get_connections():
        if connection.tenant_type == "ORGANISATION":
            return connection.id

def get_xero_tenant_id():
    token = obtain_xero_oauth2_token()
    if not token:
        return None

    identity_api = IdentityApi(api_client)
    for connection in identity_api.get_connections():
        if connection.tenant_type == "ORGANISATION":
            return connection.tenant_id


if __name__ == "__main__":
    app.run(host='localhost', port=5000)
