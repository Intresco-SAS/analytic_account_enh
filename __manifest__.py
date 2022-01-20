# -*- coding: utf-8 -*-
{
    "name": "Analytic Account Enhancement",
    "summary": "Analytic Account Enhancement in sales, invoicing, inventory etc.",
    "version": "14.0.0.1",
    "category": "Accounting",
    "depends": [
        "invoice_analytic_account",
        "stock_analytic",
        'sale_management',
        'mrp_analytic',
        'purchase',
    ],
    "data": [
        "views/view.xml"
    ],
    "installable": True,
    "application": True,
}
