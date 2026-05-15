import { Str, Num, BelongsTo } from 'pinia-orm/decorators'
import BaseModel from '~~/store/BaseModel'
import Strategy from '~~/store/models/Strategy'

export default class Position extends BaseModel {
  static entity = 'positions'

  @Str('') declare id: string
  @Str('') declare strategy_id: string
  @Str('') declare symbol: string
  @Num(0) declare qty: number
  @Num(0) declare avg_price: number
  @Num(0) declare mark_price: number
  @Num(0) declare unrealised_pnl: number
  @Str('') declare opened_at: string

  @BelongsTo(() => Strategy, 'strategy_id') declare strategy: Strategy | null
}

