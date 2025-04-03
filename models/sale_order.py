from odoo import api, fields, exceptions, models, _
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_confirm(self):        
        if self.state == 'draft' or self.state == 'sent':
            if not self.analytic_account_id:
                raise UserError(
                    _("Please add Analytic Account, in order to confirm Sale Order!"))
        super(SaleOrder, self.with_context(from_so=self.id)).action_confirm()