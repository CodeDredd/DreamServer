import { Str, HasMany } from 'pinia-orm/decorators'
import BaseModel from '~~/store/BaseModel'
import Draw from '~~/store/models/Draw'
import TipSet from '~~/store/models/TipSet'

export default class Game extends BaseModel {
  static entity = 'lotto_games'

  // 6aus49 | eurojackpot | spiel77 | super6
  @Str('') declare id: string
  @Str('') declare name: string
  @Str('') declare pool: string
  @Str('') declare days: string

  @HasMany(() => Draw, 'game_id') declare draws: Draw[]
  @HasMany(() => TipSet, 'game_id') declare tipsets: TipSet[]
}

