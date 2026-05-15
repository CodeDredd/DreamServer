import { Str, Attr, BelongsTo } from 'pinia-orm/decorators'
import BaseModel from '~~/store/BaseModel'
import Game from '~~/store/models/Game'
import Draw from '~~/store/models/Draw'

export interface LottoTip {
  numbers: number[]
  bonus?: number[]
}

export default class TipSet extends BaseModel {
  static entity = 'lotto_tipsets'

  @Str('') declare id: string
  @Str('') declare game_id: string
  // recency_exclude | frequency_hot | frequency_cold | …
  @Str('') declare strategy: string
  @Str('') declare generated_at: string
  @Str(null) declare reference_draw_id: string | null
  @Attr([]) declare tips: LottoTip[]

  @BelongsTo(() => Game, 'game_id') declare game: Game | null
  @BelongsTo(() => Draw, 'reference_draw_id') declare reference_draw: Draw | null
}

