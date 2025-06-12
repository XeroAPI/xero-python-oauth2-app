Thanks for the help Sally. I’ll give it a go.

--------------------------------


Hi Richard

In that case you can search invoices and bank transactions using the where filter and pagination and then if there is no matching invoice or transaction, then you can create the transaction.

Xero Developer Centre: BankTransactions


Kind regards

Sally



-----

The issue is that the vast majority of invoices/receipts are likely not to be in Xero (I’m referring to expenses/purchases).
So at that moment in time, in Xero, that transaction would be under “Bank Statements” section only, I believe, since it’s not yet reconciled/linked to a Payment record.

So the latter part of your suggestion makes sense, but not the first part.

Thanks for the help,
Richard


--------------------------------



Hi Richard

The best option would be to search for the invoice in Xero from the invoices endpoint and as long as you use pagination and/or include the status filter, you would retrieve details of any payments applied to the invoice.

Customers can send you a copy of their bank statements, we are contractually not allowed to.

Please note, for invoice payments you would use the payments endpoint not the bank transactions endpoint.

Xero Developer Centre:
Invoices
Payments


Kind regards

Sally


--------------------------------



Hi Richard

Dext were using the bank statements report for many years before it was deprecated and so were allowed to keep their access.

Due to contractual agreements with the banks who own the data, we can't offer the report to other apps.
Kind regards

Sally



--------------------------------


Hello,

I can see dext.com is using the bank statements report for their software (see attached OAuth screenshot). And I can see from their functionality that they are accessing the bank statement reports.

Given that fact, can you enable it for my application?

Thankyou


--------------------------------



Hi Richard

The bank statements report endpoint is deprecated and currently bank statements can only be retrieved through the bank feeds API. The bank feeds API is restricted to banks and similar regulated financial bodies that have signed a partner agreement with us.

Kind regards



-----


Hi Xero Support,


I’m using your official Python SDK to access the Bank Statement Report, but I’m running into some issues.


I’m currently using the following scopes:

```

[

"offline_access",

"accounting.contacts",

"accounting.transactions",

"accounting.attachments",

"accounting.settings",

"accounting.reports.read"

]

```

When I try to call (via your Python lib):

```

accounting_api.get_report_from_id(

xero_tenant_id=tenant_id,

report_id='BankStatement',

)

```

I get the following error:

```

*** xero_python.exceptions.http_status_exceptions.HTTPStatusException: (401)

Reason: Unauthorized

HTTP response headers:

Content-Type: application/json

Content-Length: 152

Server: nginx

WWW-Authenticate: insufficient_scope

Xero-Correlation-Id: 6a5d6db8-9495-4e0b-98dd-8b97d2c0b1e0

X-AppMinLimit-Remaining: 9997

Expires: Sun, 08 Jun 2025 14:37:32 GMT

Cache-Control: max-age=0, no-cache, no-store

Pragma: no-cache

Date: Sun, 08 Jun 2025 14:37:32 GMT

Connection: keep-alive

X-Client-TLS-ver: tls1.3

HTTP response body:

{"Type":null,"Title":"Unauthorized","Status":401,"Detail":"AuthorizationUnsuccessful","Instance":"6a5d6db8-9495-4e0b-98dd-8b97d2c0b1e0","Extensions":{} }

```


To fix this, I tried adding the `accounting.reports.bankstatement.read` scope. However, when I add that scope and re-authorize, the OAuth process fails and redirects me to the following error URL:


```

https://login.xero.com/identity/error?errorId=CfDJ8FAUJPAPyNBGj391Oz_Gl3abzhs0D5m0BeXmTYpoOAW98wOSkj7LosNbZhb2Wg2bO0bDLK6PzPfZR7IEK2E5FhSKns96Q4tiAgJ6liWIUTaYYxsb35DZ4uN-iU8ZkyEVJ2gQWn43mcm6DxrKKnAxPJa73jnk_fF3PQNQXPsV74y3NbIj2QwX5Qxck5eHQMEFvgDA2Ip7GjImPiU5-4gTreub_wIP70QgIcZw64gTpT1xXq1nWYPKCELaCOxi86OlFiLr8hE2WiXLWhO3iLAjHb5OcNP5G7xoo-4t8tg71d0HG4azMALrVqSPR0JpT-ge7aOOCoQuhqE-OJqJOKeHYfybsuddEhqg6FchNzJabOMX_1K1lR0ztob-G-Bdgp_4TbKkOr2j8YvH11R4mAquxIWal10pNuzM0ovY8zw-jXk8yt9N2mp1umLzsEOkHTquIrkwvNYlnlrA6VsRyBBWWX4LYi5JBw2DE0CaX544qAmB9WeuSwdDlll8K5z7zDOlrDwIE7juv2SDhKc0Z-GDVhTABEuxfKWfkAUWPCa75pyBXh24lFt_HcFCCkZIC0etG4uxa42ROJC5IgItJCz0kBwLnHvHkFGGCWXibYHVSKYzAv9DBAoO70CL0UA8mhtvvw

```


Could you please advise on how to proceed? Should I be using a different scope, or is there an issue with the setup on my account?


Thanks for your help!


Best regards,

Richard O'Dwyer


