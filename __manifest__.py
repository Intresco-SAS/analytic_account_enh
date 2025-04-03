# -*- coding: utf-8 -*-
{
    "name": "Analytic Account Enhancement",
    "summary": "Analytic Account Enhancement in sales, invoicing, inventory etc.",
    "version": "15.0.0.1",
    "category": "Accounting",
    "Author": "Intresco SAS",
    "depends": [
        #"invoice_analytic_account",
        "stock_analytic",
        'sale_management',
        'purchase',
        "purchase_stock_analytic",
        "purchase_analytic_global",
    ],
    "data": [
        "views/account_analytic_account_view.xml",
        "views/purchase_order_view.xml",
    ],
    "installable": True,
    "application": True,
}
