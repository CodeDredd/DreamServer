import { Str, BelongsTo, HasMany } from 'pinia-orm/decorators'
import BaseModel from '~~/store/BaseModel'
import Project from '~~/store/models/Project'
import Workflow from '~~/store/models/Workflow'

export default class RepoMapEntry extends BaseModel {
  static entity = 'repo_map_entries'

  @Str('') declare id: string
  @Str('') declare repo: string
  @Str('') declare branch: string
  @Str(null) declare project_id: string | null
  @Str('') declare last_sync: string

  @BelongsTo(() => Project, 'project_id') declare project: Project | null
  @HasMany(() => Workflow, 'repo_entry_id') declare workflows: Workflow[]
}

