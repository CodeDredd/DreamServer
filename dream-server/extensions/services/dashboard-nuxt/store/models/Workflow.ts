import { Str, Bool, BelongsTo } from 'pinia-orm/decorators'
import BaseModel from '~~/store/BaseModel'
import RepoMapEntry from '~~/store/models/RepoMapEntry'

export default class Workflow extends BaseModel {
  static entity = 'workflows'

  @Str('') declare id: string
  @Str('') declare n8n_id: string
  @Str('') declare name: string
  @Bool(false) declare active: boolean
  @Str(null) declare repo_entry_id: string | null

  @BelongsTo(() => RepoMapEntry, 'repo_entry_id') declare repo_entry: RepoMapEntry | null
}

