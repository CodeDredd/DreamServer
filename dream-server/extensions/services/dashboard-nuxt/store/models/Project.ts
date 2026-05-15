import { Str, HasMany } from 'pinia-orm/decorators'
import BaseModel from '~~/store/BaseModel'
import RepoMapEntry from '~~/store/models/RepoMapEntry'

export default class Project extends BaseModel {
  static entity = 'projects'

  @Str('') declare id: string
  @Str('') declare name: string
  @Str(null) declare vikunja_id: string | null

  @HasMany(() => RepoMapEntry, 'project_id') declare repo_entries: RepoMapEntry[]
}

