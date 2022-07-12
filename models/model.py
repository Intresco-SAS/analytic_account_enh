# -*- coding: utf-8 -*-

from odoo import api, fields, exceptions, models, _
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = "stock.move"

    @api.model
    #Función trasladar la Cuenta analitica de cada Línea de orden de Venta/Compra hacia la Entrega/Recepción.
    def create(self, vals):
        res = super(StockMove, self).create(vals)
        if res.sale_line_id and res.sale_line_id.order_id and res.sale_line_id.order_id.analytic_account_id:
            res.analytic_account_id = res.sale_line_id.order_id.analytic_account_id.id
        #Se oculta esta función hasta que se realice el desarrollo completo de Contabilidad Analitica.
        #if res.purchase_line_id and res.purchase_line_id.order_id and res.purchase_line_id.account_analytic_id:
            #res.analytic_account_id = res.purchase_line_id.account_analytic_id.id
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
                        _("Please add Analytic Account on all Invoice Lines, in order to confirm invoice!"))
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

        # purchase_order = False
        # if self.invoice_origin:
        #     purchase_order = self.env['purchase.order'].sudo().search([('name', '=', self.invoice_origin)], limit=1)
        # if self.move_type != 'entry' and purchase_order:
        if self.move_type not in ('entry'):
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
                        try:
                            to_compute = _compute_payment_terms(self, computation_date, line_dict.get(l.analytic_account_id.id).get('total_balance'), line_dict.get(l.analytic_account_id.id).get('total_amount_currency'))
                            new_terms_line = _compute_diff_payment_terms_lines(self, l, account, to_compute)
                            new_terms_line_ids.append(new_terms_line.id)
                        except:
                            pass
                for analytic_account_id, vals in line_dict.items():
                    flag_has_account = False
                    for l in existing_terms_lines:
                        if l.analytic_account_id and l.analytic_account_id.id == analytic_account_id:
                            flag_has_account = True
                    if not flag_has_account:
                        computation_date = _get_payment_terms_computation_date(self)
                        account = _get_payment_terms_account(self, self.env['account.move.line'])
                        to_compute = _compute_payment_terms(self, computation_date, vals.get('total_balance'), vals.get('total_amount_currency'))
                        new_terms_line = _compute_diff_payment_terms_lines(self, self.env['account.move.line'], account, to_compute)
                        new_terms_line.analytic_account_id = analytic_account_id
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

    # Inherited method to pass sales order id in context and Raise

    def action_confirm(self):        
        if self.state == 'draft' or self.state == 'sent':
            if not self.analytic_account_id:
                raise UserError(
                    _("Please add Analytic Account on all Sales Lines, in order to confirm Sale Order!"))
        result = super(SaleOrder, self.with_context(from_so=self.id)).action_confirm()

class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def button_confirm(self):
        if self.state == 'draft':
            for line in self.order_line:
                if not line.account_analytic_id:
                    raise UserError(
                        _("Please add Analytic Account on all Invoice Lines, in order to confirm Purchase Order!"))
        result = super(PurchaseOrder, self).button_confirm()


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
    


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    def _create_payments(self):
        self.ensure_one()
        batches = self._get_batches()
        edit_mode = self.can_edit_wizard and (len(batches[0]['lines']) == 1 or self.group_payment)

        to_reconcile = []
        if edit_mode:
            payment_vals = self._create_payment_vals_from_wizard()
            payment_vals_list = [payment_vals]
            to_reconcile.append(batches[0]['lines'])
        else:
            # Don't group payments: Create one batch per move.
            if not self.group_payment:
                new_batches = []
                for batch_result in batches:
                    for line in batch_result['lines']:
                        new_batches.append({
                            **batch_result,
                            'lines': line,
                        })
                batches = new_batches

            payment_vals_list = []
            for batch_result in batches:
                payment_vals_list.append(self._create_payment_vals_from_batch(batch_result))
                to_reconcile.append(batch_result['lines'])

        payments = self.env['account.payment'].with_context(line_ids=self.line_ids.ids).create(payment_vals_list)

        # If payments are made using a currency different than the source one, ensure the balance match exactly in
        # order to fully paid the source journal items.
        # For example, suppose a new currency B having a rate 100:1 regarding the company currency A.
        # If you try to pay 12.15A using 0.12B, the computed balance will be 12.00A for the payment instead of 12.15A.
        if edit_mode:
            for payment, lines in zip(payments, to_reconcile):
                # Batches are made using the same currency so making 'lines.currency_id' is ok.
                if payment.currency_id != lines.currency_id:
                    liquidity_lines, counterpart_lines, writeoff_lines = payment._seek_for_lines()
                    source_balance = abs(sum(lines.mapped('amount_residual')))
                    payment_rate = liquidity_lines[0].amount_currency / liquidity_lines[0].balance
                    source_balance_converted = abs(source_balance) * payment_rate

                    # Translate the balance into the payment currency is order to be able to compare them.
                    # In case in both have the same value (12.15 * 0.01 ~= 0.12 in our example), it means the user
                    # attempt to fully paid the source lines and then, we need to manually fix them to get a perfect
                    # match.
                    payment_balance = abs(sum(counterpart_lines.mapped('balance')))
                    payment_amount_currency = abs(sum(counterpart_lines.mapped('amount_currency')))
                    if not payment.currency_id.is_zero(source_balance_converted - payment_amount_currency):
                        continue

                    delta_balance = source_balance - payment_balance

                    # Balance are already the same.
                    if self.company_currency_id.is_zero(delta_balance):
                        continue

                    # Fix the balance but make sure to peek the liquidity and counterpart lines first.
                    debit_lines = (liquidity_lines + counterpart_lines).filtered('debit')
                    credit_lines = (liquidity_lines + counterpart_lines).filtered('credit')

                    payment.move_id.write({'line_ids': [
                        (1, debit_lines[0].id, {'debit': debit_lines[0].debit + delta_balance}),
                        (1, credit_lines[0].id, {'credit': credit_lines[0].credit + delta_balance}),
                    ]})

        payments.action_post()

        domain = [('account_internal_type', 'in', ('receivable', 'payable')), ('reconciled', '=', False)]
        for payment, lines in zip(payments, to_reconcile):

            # When using the payment tokens, the payment could not be posted at this point (e.g. the transaction failed)
            # and then, we can't perform the reconciliation.
            if payment.state != 'posted':
                continue

            payment_lines = payment.line_ids.filtered_domain(domain)
            for account in payment_lines.account_id:
                (payment_lines + lines)\
                    .filtered_domain([('account_id', '=', account.id), ('reconciled', '=', False)])\
                    .reconcile()

        return payments


class AccountPayment(models.Model):
    _inherit = "account.payment"

    def _synchronize_from_moves(self, changed_fields):
        ''' Update the account.payment regarding its related account.move.
        Also, check both models are still consistent.
        :param changed_fields: A set containing all modified fields on account.move.
        '''
        if self._context.get('skip_account_move_synchronization'):
            return

        for pay in self.with_context(skip_account_move_synchronization=True):

            # After the migration to 14.0, the journal entry could be shared between the account.payment and the
            # account.bank.statement.line. In that case, the synchronization will only be made with the statement line.
            if pay.move_id.statement_line_id:
                continue

            move = pay.move_id
            move_vals_to_write = {}
            payment_vals_to_write = {}

            if 'journal_id' in changed_fields:
                if pay.journal_id.type not in ('bank', 'cash'):
                    raise UserError(_("A payment must always belongs to a bank or cash journal."))

            if 'line_ids' in changed_fields:
                all_lines = move.line_ids
                liquidity_lines, counterpart_lines, writeoff_lines = pay._seek_for_lines()

                # if len(liquidity_lines) != 1 or len(counterpart_lines) != 1:
                #     raise UserError(_(
                #         "The journal entry %s reached an invalid state relative to its payment.\n"
                #         "To be consistent, the journal entry must always contains:\n"
                #         "- one journal item involving the outstanding payment/receipts account.\n"
                #         "- one journal item involving a receivable/payable account.\n"
                #         "- optional journal items, all sharing the same account.\n\n"
                #     ) % move.display_name)

                # if writeoff_lines and len(writeoff_lines.account_id) != 1:
                #     raise UserError(_(
                #         "The journal entry %s reached an invalid state relative to its payment.\n"
                #         "To be consistent, all the write-off journal items must share the same account."
                #     ) % move.display_name)

                if any(line.currency_id != all_lines[0].currency_id for line in all_lines):
                    raise UserError(_(
                        "The journal entry %s reached an invalid state relative to its payment.\n"
                        "To be consistent, the journal items must share the same currency."
                    ) % move.display_name)

                if any(line.partner_id != all_lines[0].partner_id for line in all_lines):
                    raise UserError(_(
                        "The journal entry %s reached an invalid state relative to its payment.\n"
                        "To be consistent, the journal items must share the same partner."
                    ) % move.display_name)

                if counterpart_lines.account_id.user_type_id.type == 'receivable':
                    partner_type = 'customer'
                else:
                    partner_type = 'supplier'

                liquidity_amount = sum(liquidity_lines.mapped('amount_currency'))
                if len(liquidity_lines) > 1:
                    liquidity_lines = liquidity_lines[0]
                else:
                    liquidity_lines = liquidity_lines

                move_vals_to_write.update({
                    'currency_id': liquidity_lines.currency_id.id,
                    'partner_id': liquidity_lines.partner_id.id,
                })
                payment_vals_to_write.update({
                    'amount': abs(liquidity_amount),
                    'partner_type': partner_type,
                    'currency_id': liquidity_lines.currency_id.id,
                    'destination_account_id': counterpart_lines.account_id.id,
                    'partner_id': liquidity_lines.partner_id.id,
                })
                if liquidity_amount > 0.0:
                    payment_vals_to_write.update({'payment_type': 'inbound'})
                elif liquidity_amount < 0.0:
                    payment_vals_to_write.update({'payment_type': 'outbound'})

            move.write(move._cleanup_write_orm_values(move, move_vals_to_write))
            pay.write(move._cleanup_write_orm_values(pay, payment_vals_to_write))

    def _prepare_move_line_default_vals(self, write_off_line_vals=None):
        ''' Prepare the dictionary to create the default account.move.lines for the current payment.
        :param write_off_line_vals: Optional dictionary to create a write-off account.move.line easily containing:
            * amount:       The amount to be added to the counterpart amount.
            * name:         The label to set on the line.
            * account_id:   The account on which create the write-off.
        :return: A list of python dictionary to be passed to the account.move.line's 'create' method.
        '''
        self.ensure_one()
        write_off_line_vals = write_off_line_vals or {}

        if not self.journal_id.payment_debit_account_id or not self.journal_id.payment_credit_account_id:
            raise UserError(_(
                "You can't create a new payment without an outstanding payments/receipts account set on the %s journal.",
                self.journal_id.display_name))

        # Compute amounts.
        write_off_amount_currency = write_off_line_vals.get('amount', 0.0)

        if self.payment_type == 'inbound':
            # Receive money.
            liquidity_amount_currency = self.amount
        elif self.payment_type == 'outbound':
            # Send money.
            liquidity_amount_currency = -self.amount
            write_off_amount_currency *= -1
        else:
            liquidity_amount_currency = write_off_amount_currency = 0.0

        write_off_balance = self.currency_id._convert(
            write_off_amount_currency,
            self.company_id.currency_id,
            self.company_id,
            self.date,
        )
        liquidity_balance = self.currency_id._convert(
            liquidity_amount_currency,
            self.company_id.currency_id,
            self.company_id,
            self.date,
        )
        counterpart_amount_currency = -liquidity_amount_currency - write_off_amount_currency
        counterpart_balance = -liquidity_balance - write_off_balance
        currency_id = self.currency_id.id

        if self.is_internal_transfer:
            if self.payment_type == 'inbound':
                liquidity_line_name = _('Transfer to %s', self.journal_id.name)
            else: # payment.payment_type == 'outbound':
                liquidity_line_name = _('Transfer from %s', self.journal_id.name)
        else:
            liquidity_line_name = self.payment_reference

        # Compute a default label to set on the journal items.

        payment_display_name = {
            'outbound-customer': _("Customer Reimbursement"),
            'inbound-customer': _("Customer Payment"),
            'outbound-supplier': _("Vendor Payment"),
            'inbound-supplier': _("Vendor Reimbursement"),
        }

        default_line_name = self.env['account.move.line']._get_default_line_name(
            _("Internal Transfer") if self.is_internal_transfer else payment_display_name['%s-%s' % (self.payment_type, self.partner_type)],
            self.amount,
            self.currency_id,
            self.date,
            partner=self.partner_id,
        )

        line_vals_list = []
        lines = False
        if self._context.get('line_ids'):
            lines = self.env['account.move.line'].browse(self._context.get('line_ids'))

        if lines and abs(sum(lines.mapped('amount_currency'))) == abs(self.amount):
            for l in lines:
                default_line_name = self.env['account.move.line']._get_default_line_name(
                    _("Internal Transfer") if self.is_internal_transfer else payment_display_name['%s-%s' % (self.payment_type, self.partner_type)],
                    l.amount_currency,
                    self.currency_id,
                    self.date,
                    partner=self.partner_id,
                )

                # Liquidity line.
                line_vals_list.append({
                    'name': liquidity_line_name or default_line_name,
                    'date_maturity': self.date,
                    'amount_currency': l.amount_currency,
                    'currency_id': currency_id,
                    'debit': l.amount_currency if l.amount_currency > 0.0 else 0.0,
                    'credit': -l.amount_currency if l.amount_currency < 0.0 else 0.0,
                    'partner_id': self.partner_id.id,
                    'account_id': self.journal_id.payment_credit_account_id.id if l.amount_currency < 0.0 else self.journal_id.payment_debit_account_id.id,
                    'analytic_account_id': l.analytic_account_id and l.analytic_account_id.id or False,
                })

                if counterpart_amount_currency > 0:
                    aamount_currency = abs(l.amount_currency)
                else:
                    aamount_currency = -l.amount_currency
                default_line_name = self.env['account.move.line']._get_default_line_name(
                    _("Internal Transfer") if self.is_internal_transfer else payment_display_name['%s-%s' % (self.payment_type, self.partner_type)],
                    aamount_currency,
                    self.currency_id,
                    self.date,
                    partner=self.partner_id,
                )

                # Receivable / Payable.
                line_vals_list.append({
                    'name': self.payment_reference or default_line_name,
                    'date_maturity': self.date,
                    'amount_currency': aamount_currency,
                    'currency_id': currency_id,
                    'debit': aamount_currency if aamount_currency > 0.0 else 0.0,
                    'credit': -aamount_currency if aamount_currency < 0.0 else 0.0,
                    'partner_id': self.partner_id.id,
                    'account_id': self.destination_account_id.id,
                    'analytic_account_id': l.analytic_account_id and l.analytic_account_id.id or False,
                })
        else:
            line_vals_list = [
                # Liquidity line.
                {
                    'name': liquidity_line_name or default_line_name,
                    'date_maturity': self.date,
                    'amount_currency': liquidity_amount_currency,
                    'currency_id': currency_id,
                    'debit': liquidity_balance if liquidity_balance > 0.0 else 0.0,
                    'credit': -liquidity_balance if liquidity_balance < 0.0 else 0.0,
                    'partner_id': self.partner_id.id,
                    'account_id': self.journal_id.payment_credit_account_id.id if liquidity_balance < 0.0 else self.journal_id.payment_debit_account_id.id,
                },
                # Receivable / Payable.
                {
                    'name': self.payment_reference or default_line_name,
                    'date_maturity': self.date,
                    'amount_currency': counterpart_amount_currency,
                    'currency_id': currency_id,
                    'debit': counterpart_balance if counterpart_balance > 0.0 else 0.0,
                    'credit': -counterpart_balance if counterpart_balance < 0.0 else 0.0,
                    'partner_id': self.partner_id.id,
                    'account_id': self.destination_account_id.id,
                },
            ]
        if not self.currency_id.is_zero(write_off_amount_currency):
            # Write-off line.
            line_vals_list.append({
                'name': write_off_line_vals.get('name') or default_line_name,
                'amount_currency': write_off_amount_currency,
                'currency_id': currency_id,
                'debit': write_off_balance if write_off_balance > 0.0 else 0.0,
                'credit': -write_off_balance if write_off_balance < 0.0 else 0.0,
                'partner_id': self.partner_id.id,
                'account_id': write_off_line_vals.get('account_id'),
            })
        return line_vals_list
    
class AccountAnalyticAccount(models.Model):
    _inherit = "account.analytic.account"

    @api.onchange('code')
    def _check_code(self):
        default_code = self.env['account.analytic.account'].search([('code','=',self.code)])
        if not self.code:
            return
        if default_code:
            raise exceptions.ValidationError('La Referencia de la Cuenta Analitica debe ser Única')
