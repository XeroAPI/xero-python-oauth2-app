from datetime import timedelta
from xero_python.accounting import AccountingApi


from xero_python.accounting import AccountingApi, BankTransaction, Contact, LineItem, Account


from datetime import date
from xero_python.accounting import BankTransactions
"""

Sort of auto-reconcile a bank transaction:

bank_transaction = BankTransaction(
    type="SPEND",
    contact=Contact(
        name="SMART Agency"
    ),
    line_items=[
        LineItem(
            description="Payment to SMART Agency 2",
            quantity=1,
            unit_amount=4500.00,
            account_code="400"
        )
    ],
    bank_account=Account(
        code="090"
    ),
    date=date(2025, 5, 30),
    reference="0195 0210"
)

response = accounting_api.create_bank_transactions(
    xero_tenant_id=xero_tenant_id,
    bank_transactions=BankTransactions(bank_transactions=[bank_transaction])
)

accounting_api.get_bank_transactions(xero_tenant_id, where='Total=4500 && status!="DELETED"').bank_transactions[1]

"""


def search_for_reconciliation(xero_tenant_id, api_client, target_date, target_amount):
    """
    Search for bank transactions matching specific criteria using where filter and pagination.
    If no matching transaction is found, create a new one.
    Based on Sally's suggestion from Xero support.
    Returns a tuple of (result, error_message)
    """
    accounting_api = AccountingApi(api_client)
    # Search for existing bank transactions using where filter as Sally suggested
    where_filter = f'Total=={target_amount} && Status!="DELETED"'
    print(f"Searching for bank transactions with filter: {where_filter}")

    # Since it's an Invoice OR Receipt we are searching for,
    # and since Invoice documents do not always have paid status.
    # ``target_date`` could just be the date from which the
    # invoice was created.
    where_clause = (
        f'Total=={target_amount} && '
        f'Date>=DateTime({target_date.year},{target_date.month:02d},{target_date.day:02d})'
    )

    transactions = accounting_api.get_bank_transactions(
        xero_tenant_id,
        where=where_clause,
        order="Date DESC",
        if_modified_since=target_date
    )
    invoices = accounting_api.get_invoices(
        xero_tenant_id,
        where=where_clause,
        order="Date DESC",
    )
    not_found = len(transactions.bank_transactions) == 0 and len(invoices.invoices) == 0
    not_reconciled = not_found
    if not_reconciled:
        print('Not reconciled')
    else:
        print('Reconciled')
    return {
        'bank_transactions': transactions.bank_transactions,
        'invoices': invoices.invoices,
        'is_reconciled': not not_reconciled,
    }


def find_or_create_bank_transaction(xero_tenant_id, api_client, target_date, target_amount):
    """
    Search for bank transactions matching specific criteria using where filter and pagination.
    If no matching transaction is found, create a new one.
    Based on Sally's suggestion from Xero support.
    Returns a tuple of (result, error_message)
    """
    accounting_api = AccountingApi(api_client)
    # Search for existing bank transactions using where filter as Sally suggested
    where_filter = f'Total=={target_amount} && Status!="DELETED"'
    print(f"Searching for bank transactions with filter: {where_filter}")

    # Since it's an Invoice OR Receipt we are searching for,
    # and since Invoice documents do not always have paid status.
    # ``target_date`` could just be the date from which the
    # invoice was created.
    where_clause = (
        f'Total=={target_amount} && '
        f'Date>=DateTime({target_date.year},{target_date.month:02d},{target_date.day:02d})'
    )

    transactions = accounting_api.get_bank_transactions(
        xero_tenant_id,
        where=where_clause,
        order="Date DESC",
        if_modified_since=target_date
    )
    invoices = accounting_api.get_invoices(
        xero_tenant_id,
        where=where_clause,
        order="Date DESC",
    )
    not_found = len(transactions.bank_transactions) == 0 and len(invoices.invoices) == 0
    not_reconciled = not_found
    if not_reconciled:
        print('Not reconciled')
    else:
        print('Reconciled')
    return {
        'bank_transactions': transactions.bank_transactions,
        'invoices': invoices.invoices,
        'is_reconciled': not not_reconciled,
    }

    try:
        # Search for existing bank transactions using where filter as Sally suggested
        where_filter = f'Total=={target_amount} && Status!="DELETED"'
        print(f"Searching for bank transactions with filter: {where_filter}")

        # Since it's an Invoice OR Receipt we are searching for,
        # and since Invoice documents do not always have paid status.
        # ``target_date`` could just be the date from which the
        # invoice was created.
        where_clause = (
            f'Total=={target_amount} && '
            f'Date>=DateTime({target_date.year},{target_date.month:02d},{target_date.day:02d})'
        )

        transactions = accounting_api.get_bank_transactions(
            xero_tenant_id,
            where=where_clause,
            order="Date DESC",
            if_modified_since=target_date
        )
        invoices = accounting_api.get_invoices(
            xero_tenant_id,
            where=where_clause,
            order="Date DESC",
        )
        not_found = len(transactions.bank_transactions) == 0 and len(invoices.invoices) == 0
        not_reconciled = not_found
        if not_reconciled:
            print('Not reconciled')
        else:
            print('Reconciled')
        return {
            'bank_transactions': transactions.bank_transactions,
            'invoices': invoices.invoices,
        }

        print(f"Found {len(transactions.bank_transactions)} transactions matching amount criteria")

        # Look for matches with date (reference is editable so don't require exact match)
        date_matches = []
        for tx in transactions.bank_transactions:
            # Check if date matches - this is the primary criteria since reference is editable
            if tx.date == target_date:
                date_matches.append({
                    'bank_transaction_id': tx.bank_transaction_id,
                    'total': tx.total,
                    'reference': tx.reference,
                    'contact_name': tx.contact.name if tx.contact else None,
                    'date': tx.date.isoformat() if tx.date else None,
                    'status': tx.status,
                    'type': tx.type,
                    'is_reconciled': tx.is_reconciled,
                })

        if date_matches:
            print(f"Found {len(date_matches)} transactions matching date and amount")
            return {'action': 'found', 'transactions': date_matches}, None

        # No matching transaction found, create a new one as Sally suggested
        print("No matching transaction found. Creating new bank transaction...")

        bank_transaction = BankTransaction(
            type="SPEND",
            contact=Contact(
                name="SMART Agency"
            ),
            line_items=[
                LineItem(
                    description="Payment to SMART Agency",
                    quantity=1,
                    unit_amount=target_amount,
                    account_code="400"  # Default expense account
                )
            ],
            bank_account=Account(
                code="090"  # Default bank account
            ),
            date=target_date,
            reference="SMART Agency"
        )

        response = accounting_api.create_bank_transactions(
            xero_tenant_id=xero_tenant_id,
            bank_transactions=BankTransactions(bank_transactions=[bank_transaction])
        )

        if response.bank_transactions:
            created_tx = response.bank_transactions[0]
            result = {
                'action': 'created',
                'transaction': {
                    'bank_transaction_id': created_tx.bank_transaction_id,
                    'total': created_tx.total,
                    'reference': created_tx.reference,
                    'contact_name': created_tx.contact.name if created_tx.contact else None,
                    'date': created_tx.date.isoformat() if created_tx.date else None,
                    'status': created_tx.status,
                    'type': created_tx.type,
                }
            }
            print(f"Successfully created bank transaction: {created_tx.bank_transaction_id}")
            return result, None
        else:
            return None, "Failed to create bank transaction"

    except Exception as e:
        print(f"Error details: {str(e)}")
        return None, f"Unexpected error: {str(e)}"
