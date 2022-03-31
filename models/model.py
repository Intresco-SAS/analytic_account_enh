# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import UserError


class StockMove(models.Model):
    _inherit = "stock.move"

    @api.model
    def create(self, vals):
        res = super(StockMove, self).create(vals)
        if res.sale_line_id and res.sale_line_id.order_id and res.sale_line_id.order_id.analytic_account_id:
            res.analytic_account_id = res.sale_line_id.order_id.analytic_account_id.id
        if res.purchase_line_id and res.purchase_line_id.order_id and res.purchase_line_id.account_analytic_id:
            res.analytic_account_id = res.purchase_line_id.account_analytic_id.id
        return res


class AccountMove(models.Model):
    _inherit = "account.move"

    @api.model
    def create(self, vals):
        res = super(AccountMove, self).create(vals)
        if res.invoice_origin:
            order = self.env['sale.order'].sudo().search(
                [('name', '=', res.invoice_origin)], limit=1)
            if order and order.analytic_account_id:
                res.analytic_account_id = order.analytic_account_id.id
        return res

    def action_post(self):
        if self.move_type == 'out_invoice':
            for line in self.invoice_line_ids:
                if not line.analytic_account_id:
                    raise UserError(
                        "Please add Analytic Account on all Invoice Lines, in order to confirm invoice!")
        result = super(AccountMove, self).action_post()
        for res in self.line_ids:
            if self.analytic_account_id:
                if res.name == self.name and res.debit > 0 and not res.analytic_account_id:
                    res.analytic_account_id = self.analytic_account_id.id
                if res.credit > 0 and not res.analytic_account_id:
                    res.analytic_account_id = self.analytic_account_id.id
        return result

    def _recompute_payment_terms_lines(self):
        ''' Compute the dynamic payment term lines of the journal entry.'''
        self.ensure_one()
        self = self.with_company(self.company_id)
        in_draft_mode = self != self._origin
        today = fields.Date.context_today(self)
        self = self.with_company(self.journal_id.company_id)

        def _get_payment_terms_computation_date(self):
            ''' Get the date from invoice that will be used to compute the payment terms.
            :param self:    The current account.move record.
            :return:        A datetime.date object.
            '''
            if self.invoice_payment_term_id:
                return self.invoice_date or today
            else:
                return self.invoice_date_due or self.invoice_date or today

        def _get_payment_terms_account(self, payment_terms_lines):
            ''' Get the account from invoice that will be set as receivable / payable account.
            :param self:                    The current account.move record.
            :param payment_terms_lines:     The current payment terms lines.
            :return:                        An account.account record.
            '''
            if payment_terms_lines:
                # Retrieve account from previous payment terms lines in order to allow the user to set a custom one.
                return payment_terms_lines[0].account_id
            elif self.partner_id:
                # Retrieve account from partner.
                if self.is_sale_document(include_receipts=True):
                    return self.partner_id.property_account_receivable_id
                else:
                    return self.partner_id.property_account_payable_id
            else:
                # Search new account.
                domain = [
                    ('company_id', '=', self.company_id.id),
                    ('internal_type', '=', 'receivable' if self.move_type in ('out_invoice', 'out_refund', 'out_receipt') else 'payable'),
                ]
                return self.env['account.account'].search(domain, limit=1)

        def _compute_payment_terms(self, date, total_balance, total_amount_currency):
            ''' Compute the payment terms.
            :param self:                    The current account.move record.
            :param date:                    The date computed by '_get_payment_terms_computation_date'.
            :param total_balance:           The invoice's total in company's currency.
            :param total_amount_currency:   The invoice's total in invoice's currency.
            :return:                        A list <to_pay_company_currency, to_pay_invoice_currency, due_date>.
            '''
            if self.invoice_payment_term_id:
                to_compute = self.invoice_payment_term_id.compute(total_balance, date_ref=date, currency=self.company_id.currency_id)
                if self.currency_id == self.company_id.currency_id:
                    # Single-currency.
                    return [(b[0], b[1], b[1]) for b in to_compute]
                else:
                    # Multi-currencies.
                    to_compute_currency = self.invoice_payment_term_id.compute(total_amount_currency, date_ref=date, currency=self.currency_id)
                    return [(b[0], b[1], ac[1]) for b, ac in zip(to_compute, to_compute_currency)]
            else:
                return [(fields.Date.to_string(date), total_balance, total_amount_currency)]

        def _compute_diff_payment_terms_lines(self, existing_terms_lines, account, to_compute):
            ''' Process the result of the '_compute_payment_terms' method and creates/updates corresponding invoice lines.
            :param self:                    The current account.move record.
            :param existing_terms_lines:    The current payment terms lines.
            :param account:                 The account.account record returned by '_get_payment_terms_account'.
            :param to_compute:              The list returned by '_compute_payment_terms'.
            '''
            # As we try to update existing lines, sort them by due date.
            existing_terms_lines = existing_terms_lines.sorted(lambda line: line.date_maturity or today)
            existing_terms_lines_index = 0

            # Recompute amls: update existing line or create new one for each payment term.
            new_terms_lines = self.env['account.move.line']
            for date_maturity, balance, amount_currency in to_compute:
                currency = self.journal_id.company_id.currency_id
                if currency and currency.is_zero(balance) and len(to_compute) > 1:
                    continue

                if existing_terms_lines_index < len(existing_terms_lines):
                    # Update existing line.
                    candidate = existing_terms_lines[existing_terms_lines_index]
                    existing_terms_lines_index += 1
                    candidate.update({
                        'date_maturity': date_maturity,
                        'amount_currency': -amount_currency,
                        'debit': balance < 0.0 and -balance or 0.0,
                        'credit': balance > 0.0 and balance or 0.0,
                    })
                else:
                    # Create new line.
                    create_method = in_draft_mode and self.env['account.move.line'].new or self.env['account.move.line'].create
                    candidate = create_method({
                        'name': self.payment_reference or '',
                        'debit': balance < 0.0 and -balance or 0.0,
                        'credit': balance > 0.0 and balance or 0.0,
                        'quantity': 1.0,
                        'amount_currency': -amount_currency,
                        'date_maturity': date_maturity,
                        'move_id': self.id,
                        'currency_id': self.currency_id.id,
                        'account_id': account.id,
                        'partner_id': self.commercial_partner_id.id,
                        'exclude_from_invoice_tab': True,
                    })
                new_terms_lines += candidate
                if in_draft_mode:
                    candidate.update(candidate._get_fields_onchange_balance(force_computation=True))
            return new_terms_lines

        existing_terms_lines = self.line_ids.filtered(lambda line: line.account_id.user_type_id.type in ('receivable', 'payable'))
        others_lines = self.line_ids.filtered(lambda line: line.account_id.user_type_id.type not in ('receivable', 'payable'))
        company_currency_id = (self.company_id or self.env.company).currency_id
        total_balance = sum(others_lines.mapped(lambda l: company_currency_id.round(l.balance)))
        total_amount_currency = sum(others_lines.mapped('amount_currency'))

        if not others_lines:
            self.line_ids -= existing_terms_lines
            return

        purchase_order = False
        if self.invoice_origin:
            purchase_order = self.env['purchase.order'].sudo().search([('name', '=', self.invoice_origin)], limit=1)
        if purchase_order and self.move_type == 'in_invoice':
            line_dict = {}
            new_terms_line_ids = []
            for l in others_lines:
                if l.analytic_account_id and line_dict.get(l.analytic_account_id.id):
                    total_balancee = line_dict[l.analytic_account_id.id].get('total_balance') + sum(l.mapped(lambda l: company_currency_id.round(l.balance)))
                    total_amount_currencyy = line_dict[l.analytic_account_id.id].get('total_amount_currency') + sum(l.mapped('amount_currency'))

                    line_dict[l.analytic_account_id.id] = {
                        'total_balance': total_balancee,
                        'total_amount_currency': total_amount_currencyy,
                    }
                else:
                    line_dict[l.analytic_account_id.id] = {
                        'total_balance': sum(l.mapped(lambda l: company_currency_id.round(l.balance))),
                        'total_amount_currency': sum(l.mapped('amount_currency')),
                    }
            if not existing_terms_lines:
                for analytic_account_id, vals in line_dict.items():
                    computation_date = _get_payment_terms_computation_date(self)
                    account = _get_payment_terms_account(self, existing_terms_lines)
                    to_compute = _compute_payment_terms(self, computation_date, vals.get('total_balance'), vals.get('total_amount_currency'))
                    new_terms_line = _compute_diff_payment_terms_lines(self, existing_terms_lines, account, to_compute)
                    new_terms_line.analytic_account_id = analytic_account_id
                    new_terms_line_ids.append(new_terms_line.id)
            else:
                for l in existing_terms_lines:
                    if l.analytic_account_id:
                        computation_date = _get_payment_terms_computation_date(self)
                        account = _get_payment_terms_account(self, l)
                        to_compute = _compute_payment_terms(self, computation_date, line_dict.get(l.analytic_account_id.id).get('total_balance'), line_dict.get(l.analytic_account_id.id).get('total_amount_currency'))
                        new_terms_line = _compute_diff_payment_terms_lines(self, l, account, to_compute)
                        new_terms_line_ids.append(new_terms_line.id)
            new_terms_lines = self.env['account.move.line'].sudo().browse(new_terms_line_ids)
        else:
            computation_date = _get_payment_terms_computation_date(self)
            account = _get_payment_terms_account(self, existing_terms_lines)
            to_compute = _compute_payment_terms(self, computation_date, total_balance, total_amount_currency)
            new_terms_lines = _compute_diff_payment_terms_lines(self, existing_terms_lines, account, to_compute)

        # Remove old terms lines that are no longer needed.
        self.line_ids -= existing_terms_lines - new_terms_lines

        if new_terms_lines:
            self.payment_reference = new_terms_lines[-1].name or ''
            self.invoice_date_due = new_terms_lines[-1].date_maturity


class SaleOrder(models.Model):
    _inherit = "sale.order"

    # Inherited method to pass sales order id in context
    def action_confirm(self):
        res = super(SaleOrder, self.with_context(from_so=self.id)).action_confirm()
        return res

    '''def action_confirm(self):
        super(SaleOrder, self).action_confirm()
        if self.state == 'sale':
            if not self.analytic_account_id:
                raise UserError(
                    "Please add Analytic Account on all Sales Lines, in order to confirm invoice!")'''

    def action_post_sale(self):
        res = super(SaleOrder, self).action_confirm()
        if self.state == 'draft' or self.state == 'sent':
            if not self.analytic_account_id:
                raise UserError(
                    "Please add Analytic Account on all Sales Lines, in order to confirm invoice!")
        return res


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    @api.model
    def create(self, vals):
        # To set analytic account on manufacturing order from sales order
        if self._context.get('from_so'):
            so = self.env['sale.order'].sudo().browse(self._context.get('from_so'))
            if so and so.analytic_account_id:
                vals['analytic_account_id'] = so.analytic_account_id.id
        res = super(MrpProduction, self).create(vals)
        return res


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    @api.model
    def create(self, vals):
        # To set analytic account on purchase order lines from sales order
        if self._context.get('from_so'):
            so = self.env['sale.order'].sudo().browse(self._context.get('from_so'))
            if so and so.analytic_account_id:
                vals['account_analytic_id'] = so.analytic_account_id.id
        res = super(PurchaseOrderLine, self).create(vals)
        return res
