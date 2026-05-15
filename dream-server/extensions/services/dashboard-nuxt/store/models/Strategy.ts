import { Str, Num, Bool, HasMany } from 'pinia-orm/decorators'
import BaseModel from '~~/store/BaseModel'
import Position from '~~/store/models/Position'
import Trade from '~~/store/models/Trade'

export default class Strategy extends BaseModel {
  static entity = 'strategies'

  @Str('') declare id: string
  @Str('') declare name: string
  @Str('') declare kind: string // momentum | mean_reversion | news_sentiment …
  @Bool(true) declare enabled: boolean
  @Num(1000) declare seeded: number
  @Num(0) declare equity: number
  @Num(0) declare pnl: number

  @HasMany(() => Position, 'strategy_id') declare positions: Position[]
  @HasMany(() => Trade, 'strategy_id') declare trades: Trade[]
}

