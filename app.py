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
from xero_python.accounting import AccountingApi, Account, Accounts, AccountType, BankTransaction, BankTransactions, BankTransfer, BankTransfers, Contact, ContactPerson, Contacts, Invoice, Invoices, LineItem
from xero_python.assets import AssetApi, Asset, AssetStatus, AssetStatusQueryParam, AssetType, BookDepreciationSetting
from xero_python.project import ProjectApi, Projects, ProjectCreateOrUpdate, ProjectPatch, ProjectStatus, ProjectUsers, TimeEntryCreateOrUpdate
from xero_python.payrollau import PayrollAuApi, Employees, Employee, EmployeeStatus,State, HomeAddress
from xero_python.payrolluk import PayrollUkApi, Employees, Employee, Address, Employment
from xero_python.payrollnz import PayrollNzApi, Employees, Employee, Address, Employment, EmployeeLeaveSetup
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

# ACCOUNTS TODO
# getAccounts x
# createAccount x
# getAccount x
# updateAccount x
# deleteAccount x
# getAccountAttachments
# getAccountAttachmentById
# getAccountAttachmentByFileName
# updateAccountAttachmentByFileName
# createAccountAttachmentByFileName x

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
            myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
            with myimage.open("rb") as image:
                account_attachment_created = accounting_api.create_account_attachment_by_file_name(
                    xero_tenant_id,
                    account_id,
                    file_name=myimage.name,
                    body=image.read(),
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
        myimage = Path(__file__).resolve().parent.joinpath("helo-heros.jpg")
        with myimage.open("rb") as image:
            account_attachment_created = accounting_api.create_account_attachment_by_file_name(
                xero_tenant_id,
                account_id,
                file_name=myimage.name,
                body=image.read(),
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

# BANK TRANSACTIONS TODO
# getBankTransactions x
# createBankTransactions x
# updateOrCreateBankTransactions
# getBankTransaction x
# updateBankTransaction
# getBankTransactionAttachments
# getBankTransactionAttachmentById
# getBankTransactionAttachmentByFileName
# updateBankTransactionAttachmentByFileName
# createBankTransactionAttachmentByFileName
# getBankTransactionsHistory
# createBankTransactionHistoryRecord

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

# BANK TRANSFERS TODO
# getBankTransfers x
# createBankTransfer
# getBankTransfer x
# getBankTransferAttachments
# getBankTransferAttachmentById
# getBankTransferAttachmentByFileName
# updateBankTransferAttachmentByFileName
# createBankTransferAttachmentByFileName
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

# BATCH PAYMENTS TODO
# getBatchPayments x
# createBatchPayment
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

# BRANDING THEMES TODO
# getBrandingThemes x
# getBrandingTheme x
# getBrandingThemePaymentServices
# createBrandingThemePaymentServices

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

# BUDGETS TODO
# *** coming April 2021 ***

# CONTACTS TODO
# getContacts x
# createContacts x
# updateOrCreateContacts
# getContactByContactNumber
# getContact x
# updateContact
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
            getvalue(read_contacts, "contacts.0.contact_id", "")
        )
        json = serialize_model(read_one_contact)
    #[/CONTACTS:READ_ONE]

    return render_template(
        "output.html", title="Contacts", code=code, json=json, output=output, len = 0, set="accounting", endpoint="contact", action="read_one"
    )

# CONTACT GROUPS TODO
# getContactGroups x
# createContactGroup
# getContactGroup x
# updateContactGroup
# createContactGroupContacts
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

# CREDIT NOTES TODO
# getCreditNotes x
# createCreditNotes
# updateOrCreateCreditNotes
# getCreditNote x
# updateCreditNote
# getCreditNoteAttachments
# getCreditNoteAttachmentById
# getCreditNoteAttachmentByFileName
# updateCreditNoteAttachmentByFileName
# createCreditNoteAttachmentByFileName
# getCreditNoteAsPdf
# createCreditNoteAllocation
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

# CURRENCIES TODO
# getCurrencies x
# createCurrency

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

# EMPLOYEES TODO
# getEmployees x
# createEmployees
# updateOrCreateEmployees
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

# EXPENSE CLAIMS (DEPRECATED) TODO
# getExpenseClaims x
# createExpenseClaims
# getExpenseClaim x
# updateExpenseClaim
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

# INVOICES TODO
# getInvoices x
# createInvoices x
# updateOrCreateInvoices
# getInvoice x
# updateInvoice
# getInvoiceAsPdf
# getInvoiceAttachments
# getInvoiceAttachmentById
# getInvoiceAttachmentByFileName
# updateInvoiceAttachmentByFileName
# createInvoiceAttachmentByFileName
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

# INVOICE REMINDERS TODO
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
# createItems
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

# JOURNALS TODO
# getJournals
# getJournal

# LINKED TRANSACTIONS TODO
# getLinkedTransactions
# createLinkedTransaction
# getLinkedTransaction
# updateLinkedTransaction
# deleteLinkedTransaction

# MANUAL JOURNALS TODO
# getManualJournals
# createManualJournals
# updateOrCreateManualJournals
# getManualJournal
# updateManualJournal
# getManualJournalAttachments
# getManualJournalAttachmentById
# getManualJournalAttachmentByFileName
# updateManualJournalAttachmentByFileName
# createManualJournalAttachmentByFileName

# ORGANISATION TODO
# getOrganisations
# getOrganisationCISSettings

# OVERPAYMENTS TODO 
# getOverpayments
# getOverpayment
# createOverpaymentAllocations
# getOverpaymentHistory
# createOverpaymentHistory

# PAYMENTS TODO
# getPayments
# createPayments
# createPayment
# getPayment
# deletePayment
# getPaymentHistory
# createPaymentHistory

# PAYMENT SERVICES TODO
# getPaymentServices
# createPaymentService

# PREPAYMENTS TODO
# getPrepayments
# getPrepayment
# createPrepaymentAllocations
# getPrepaymentHistory
# createPrepaymentHistory

# PURCHASE ORDERS TODO
# getPurchaseOrders
# createPurchaseOrders
# updateOrCreatePurchaseOrders
# getPurchaseOrderAsPdf
# getPurchaseOrder
# updatePurchaseOrder
# getPurchaseOrderByNumber
# getPurchaseOrderHistory
# createPurchaseOrderHistory

# QUOTES TODO
# getQuotes
# createQuotes
# updateOrCreateQuotes
# getQuote
# updateQuote
# getQuoteHistory
# createQuoteHistory
# getQuoteAsPdf
# getQuoteAttachments
# getQuoteAttachmentById
# getQuoteAttachmentByFileName
# updateQuoteAttachmentByFileName
# createQuoteAttachmentByFileName

# RECEIPTS (DEPRECATED) TODO
# getReceipts
# createReceipt
# getReceipt
# updateReceipt
# getReceiptAttachments
# getReceiptAttachmentById
# getReceiptAttachmentByFileName
# updateReceiptAttachmentByFileName
# createReceiptAttachmentByFileName
# getReceiptHistory
# createReceiptHistory

# REPEATING INVOICES TODO
# getRepeatingInvoices
# getRepeatingInvoice
# getRepeatingInvoiceAttachments
# getRepeatingInvoiceAttachmentById
# getRepeatingInvoiceAttachmentByFileName
# updateRepeatingInvoiceAttachmentByFileName
# createRepeatingInvoiceAttachmentByFileName
# getRepeatingInvoiceHistory
# createRepeatingInvoiceHistory

# REPORTS TODO
# getReportTenNinetyNine
# getReportAgedPayablesByContact
# getReportAgedReceivablesByContact
# getReportBalanceSheet
# getReportBankSummary
# getReportBASorGSTList
# getReportBASorGST
# getReportBudgetSummary
# getReportExecutiveSummary
# getReportProfitAndLoss
# getReportTrialBalance

# TAX RATES TODO
# getTaxRates x
# createTaxRates
# updateTaxRate
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

# TRACKING CATEGORIES TODO
# getTrackingCategories
# createTrackingCategory
# getTrackingCategory
# updateTrackingCategory
# deleteTrackingCategory
# createTrackingOptions
# updateTrackingOptions
# deleteTrackingOptions

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
