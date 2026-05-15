import { Str, BelongsTo } from 'pinia-orm/decorators'
import BaseModel from '~~/store/BaseModel'
import Service from '~~/store/models/Service'

export default class Resource extends BaseModel {
  static entity = 'resources'

  @Str('') declare id: string
  @Str('') declare service_id: string
  @Str('') declare kind: string // cpu | memory | gpu | port | volume
  @Str('') declare label: string
  @Str('') declare value: string

  @BelongsTo(() => Service, 'service_id') declare service: Service | null
}

