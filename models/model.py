# -*- coding: utf-8 -*-

from odoo import api, fields, exceptions, models, _
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)

class AccountAnalyticAccount(models.Model):
    _inherit = "account.analytic.account"

    @api.onchange('code')
    def _check_code(self):
        default_code = self.env['account.analytic.account'].search([('code','=',self.code)])
        if not self.code:
            return
        if default_code:
            raise exceptions.ValidationError('La Referencia de la Cuenta Analitica debe ser Única')
    
class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_confirm(self):        
        if self.state == 'draft' or self.state == 'sent':
            if not self.analytic_account_id:
                raise UserError(
                    _("Please add Analytic Account, in order to confirm Sale Order!"))
        super(SaleOrder, self.with_context(from_so=self.id)).action_confirm()

class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def button_confirm(self):
        if self.state == 'draft':
            for line in self.order_line:
                if not line.account_analytic_id:
                    raise UserError(
                        _("Please add Analytic Account on all lines, in order to confirm Purchase Order!"))
        super(PurchaseOrder, self).button_confirm()

class StockMove(models.Model):
    _inherit = "stock.move"

    @api.model
    #Función trasladar la Cuenta analitica de cada Línea de orden de Venta hacia la Entrega.
    def create(self, vals):
        res = super(StockMove, self).create(vals)
        if res.sale_line_id and res.sale_line_id.order_id and res.sale_line_id.order_id.analytic_account_id:
            res.analytic_account_id = res.sale_line_id.order_id.analytic_account_id.id
        return res

# class AccountMove(models.Model):
#     _inherit = "account.move"

    # @api.model
    # def create(self, vals):
    #     res = super(AccountMove, self).create(vals)
    #     if res.invoice_origin:
    #         order = self.env['sale.order'].sudo().search(
    #             [('name', '=', res.invoice_origin)], limit=1)
    #         if order and order.analytic_account_id:
    #             res.analytic_account_id = order.analytic_account_id.id
    #     return res

    # def action_post(self):
    #     if self.move_type == 'out_invoice':
    #         for line in self.invoice_line_ids:
    #             if not line.analytic_account_id:
    #                 raise UserError(
    #                     _("Please add Analytic Account on all Invoice Lines, in order to confirm invoice!"))
    #     result = super(AccountMove, self).action_post()
    #     for res in self.line_ids:
    #         if self.analytic_account_id:
    #             if res.name == self.name and res.debit > 0 and not res.analytic_account_id:
    #                 res.analytic_account_id = self.analytic_account_id.id
    #             if res.credit > 0 and not res.analytic_account_id:
    #                 res.analytic_account_id = self.analytic_account_id.id
    #     return result




# class MrpProduction(models.Model):
#     _inherit = "mrp.production"

#     @api.model
#     def create(self, vals):
#         # To set analytic account on manufacturing order from sales order
#         if self._context.get('from_so'):
#             so = self.env['sale.order'].sudo().browse(self._context.get('from_so'))
#             if so and so.analytic_account_id:
#                 vals['analytic_account_id'] = so.analytic_account_id.id
#         res = super(MrpProduction, self).create(vals)
#         return res


# class PurchaseOrderLine(models.Model):
#     _inherit = "purchase.order.line"

#     @api.model
#     def create(self, vals):
#         # To set analytic account on purchase order lines from sales order
#         if self._context.get('from_so'):
#             so = self.env['sale.order'].sudo().browse(self._context.get('from_so'))
#             if so and so.analytic_account_id:
#                 vals['account_analytic_id'] = so.analytic_account_id.id
#         res = super(PurchaseOrderLine, self).create(vals)
#         return res
    

