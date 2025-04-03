from odoo import api, fields, exceptions, models, _
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)

class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    acc_analytic_id = fields.Many2one('account.analytic.account', string='Cuenta Analítica', related='order_line.account_analytic_id')

    def button_confirm(self):
        if self.state == 'draft':
            for line in self.order_line:
                if not line.account_analytic_id:
                    raise UserError(
                        _("Please add Analytic Account on all lines, in order to confirm Purchase Order!"))
        super(PurchaseOrder, self).button_confirm()