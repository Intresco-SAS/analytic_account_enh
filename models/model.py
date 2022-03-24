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


class SaleOrder(models.Model):
    _inherit = "sale.order"

    # Inherited method to pass sales order id in context
    def action_confirm(self):
        res = super(SaleOrder, self.with_context(from_so=self.id)).action_confirm()
        return res

    def action_post_sale(self):
        if self.state == 'sale':
            for line in self.analytic_account_id:
                if not line.name:
                    raise UserError(
                        "Please add Analytic Account on all Sales Lines, in order to confirm invoice!")


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
