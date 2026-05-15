import { Str, Num, BelongsTo } from 'pinia-orm/decorators'
import BaseModel from '~~/store/BaseModel'
import Strategy from '~~/store/models/Strategy'
import Position from '~~/store/models/Position'

export default class Trade extends BaseModel {
  static entity = 'trades'

  @Str('') declare id: string
  @Str('') declare strategy_id: string
  @Str(null) declare position_id: string | null
  @Str('') declare symbol: string
  @Str('buy') declare side: 'buy' | 'sell'
  @Num(0) declare qty: number
  @Num(0) declare price: number
  @Num(0) declare pnl: number
  @Str('') declare reason: string
  @Str('') declare executed_at: string

  @BelongsTo(() => Strategy, 'strategy_id') declare strategy: Strategy | null
  @BelongsTo(() => Position, 'position_id') declare position: Position | null
}

