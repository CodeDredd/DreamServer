import { Str, Num, Attr, BelongsTo } from 'pinia-orm/decorators'
import BaseModel from '~~/store/BaseModel'
import Game from '~~/store/models/Game'

export default class Draw extends BaseModel {
  static entity = 'lotto_draws'

  @Str('') declare id: string
  @Str('') declare game_id: string
  @Str('') declare drawn_at: string
  @Attr([]) declare numbers: number[]
  @Attr(null) declare bonus: number[] | null
  @Num(0) declare jackpot: number

  @BelongsTo(() => Game, 'game_id') declare game: Game | null
}

