# -*- coding: utf8 -*-
#
# Copyright (C) 2015 NDP Systèmes (<http://www.ndp-systemes.fr>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

from openerp import models, fields, api, exceptions, _
from openerp.tools import float_compare


class StockChangeQuantPicking(models.TransientModel):
    _name = 'stock.quant.picking'

    @api.model
    def default_get(self, fields_list):
        quants = self.env['stock.quant'].browse(self.env.context['active_ids'])
        products = quants.mapped('product_id')
        if len(products) != 1:
            raise exceptions.except_orm(_("Error!"), _("Impossible to reserve quants of different products."))
        return {}

    partner_id = fields.Many2one('res.partner', string='Partner')
    picking_id = fields.Many2one('stock.picking', string='Picking', context={'reserving_quant': True})
    move_id = fields.Many2one('stock.move', string='Stock move', required=True, context={'reserving_quant': True})

    @api.onchange('partner_id')
    def onchange_partner_id(self):
        self.ensure_one()
        self.picking_id = False
        self.move_id = False
        quant = self.env['stock.quant'].browse(self.env.context['active_ids'][0])
        move_domain = [('picking_id', '!=', False),
                       ('product_id', '=', quant.product_id.id),
                       ('state', 'in', ['confirmed', 'waiting', 'assigned']),
                       ('location_id', '=', quant.location_id.id)]
        if self.partner_id:
            groups = self.env['procurement.group'].search([('partner_id', '=', self.partner_id.id)])
            move_domain += [('picking_id.group_id', 'in', groups.ids)]
        moves = self.env['stock.move'].search(move_domain)
        picking_domain = [('id', 'in', moves.mapped('picking_id').ids)]
        return {'domain': {'picking_id': picking_domain, 'move_id': move_domain}}

    @api.onchange('picking_id')
    def onchange_picking_id(self):
        self.ensure_one()
        self.move_id = False
        quant = self.env['stock.quant'].browse(self.env.context['active_ids'][0])
        move_domain = [('product_id', '=', quant.product_id.id),
                       ('state', 'in', ['confirmed', 'waiting', 'assigned']),
                       ('location_id', '=', quant.location_id.id)]
        if self.picking_id.group_id:
            move_domain += [('group_id', '=', self.picking_id.group_id.id)]
        return {'domain': {'move_id': move_domain}}

    @api.multi
    def do_apply(self):
        self.ensure_one()
        quants_ids = self.env.context.get('active_ids', [])
        quants = self.env['stock.quant'].browse(quants_ids)
        self.env['stock.quant'].quants_unreserve(self.move_id)
        quants_qty = sum([quant.qty for quant in quants])
        if float_compare(quants_qty, self.move_id.product_qty, precision_rounding=quant.product_id.uom_id.rounding) > 0:
            raise exceptions.except_orm(_("Error!"), _("Impossible to reserve more than the move quantity."))
        recalculate_state_for_moves = self.env['stock.move']
        list_reservations = []
        for quant in quants:
            move = quant.reservation_id
            parent_move = quant.history_ids.filtered(lambda sm: sm.state == 'done' and
                                                                sm.location_dest_id == quant.location_id)
            if parent_move and len(parent_move) == 1 and parent_move.move_dest_id and self.move_id.state == 'waiting':
                parent_move.move_dest_id = self.move_id
            self.move_id.action_confirm()
            list_reservations += [(quant, quant.qty)]
            if move:
                recalculate_state_for_moves += move
        self.env['stock.quant'].quants_reserve(list_reservations, self.move_id)
        if recalculate_state_for_moves:
            recalculate_state_for_moves.recalculate_move_state()
        if self.picking_id.pack_operation_ids:
            self.move_id.picking_id.do_prepare_partial()
        return {
            'name': 'Stock Operation',
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'stock.picking',
            'res_id': self.move_id.picking_id.id
        }
