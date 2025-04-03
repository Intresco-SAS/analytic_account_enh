from odoo import api, fields, exceptions, models, _
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)

class StockMove(models.Model):
    _inherit = "stock.move"

    @api.model
    #Función trasladar la Cuenta analitica de cada Línea de orden de Venta hacia la Entrega.
    def create(self, vals):
        res = super(StockMove, self).create(vals)
        if res.sale_line_id and res.sale_line_id.order_id and res.sale_line_id.order_id.analytic_account_id:
            res.analytic_account_id = res.sale_line_id.order_id.analytic_account_id.id
        return res