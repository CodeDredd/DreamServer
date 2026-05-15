import { Str, Num, HasMany } from 'pinia-orm/decorators'
import BaseModel from '~~/store/BaseModel'
import Resource from '~~/store/models/Resource'
import Token from '~~/store/models/Token'

export default class Service extends BaseModel {
  static entity = 'services'

  @Str('') declare id: string
  @Str('') declare name: string
  @Str('unknown') declare status: string
  @Str('optional') declare category: string
  @Num(0) declare port: number
  @Num(0) declare uptime: number
  @Str(null) declare backend: string | null

  @HasMany(() => Resource, 'service_id') declare resources: Resource[]
  @HasMany(() => Token, 'service_id') declare tokens: Token[]
}

