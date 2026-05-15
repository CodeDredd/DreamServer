import { Str, BelongsTo } from 'pinia-orm/decorators'
import BaseModel from '~~/store/BaseModel'
import Service from '~~/store/models/Service'

export default class Token extends BaseModel {
  static entity = 'tokens'

  @Str('') declare id: string
  @Str('') declare service_id: string
  @Str('') declare name: string
  @Str('') declare scope: string
  @Str('') declare created_at: string

  @BelongsTo(() => Service, 'service_id') declare service: Service | null
}

