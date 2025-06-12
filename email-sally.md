

What you suggested doesn't seem to work:

1)
I'm using the Demo Company, it has some unreconciled transactions.

e.g.
Jakaranda Maple Systems, 2000GBP, 30 May 2025,



2)
I query for this one using the Python library:

```
transactions = accounting_api.get_bank_transactions(
    xero_tenant_id,
    where=f'Total==2000.00 && Status!="DELETED"',
    order="Date DESC"
)
invoices = accounting_api.get_invoices(
    xero_tenant_id,
    where=f'Total==2000.00 && Status!="DELETED"',
    order="Date DESC"
)
```

3)
The result is

No transactions:

```
{'bank_transactions': [], 'pagination': None, 'warnings': None}
```

1 invoice returned but it's NOT the correct unreconciled payment:

ipdb> invoices.invoices[0].to_dict()['contact']['name']
'SMART Agency'
ipdb> invoices.invoices[0].to_dict()['total']
Decimal('2000.00')
```

Despite them showing on the UI.


----

So searching for that unreconciled payment via `get_bank_transactions` or `get_invoices` does not return what we're looking for.




