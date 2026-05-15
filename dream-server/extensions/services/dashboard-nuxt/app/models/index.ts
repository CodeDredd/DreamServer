// Pinia-ORM Entity-Layer.
//
// Hier wohnen alle relationalen Entities. UI-only-State (Sidebar,
// Splash, Theme) bleibt absichtlich in den klassischen Pinia-Stores
// (`stores/ui.ts`).
//
// Phase 2 liefert die Schema-Skelette (Felder + Relationen). Die
// jeweiligen Pages der Phase 4 verdrahten die Repositories
// (`useRepo(Service).save(payload)`), sobald sie migriert sind.
//
// Konvention:
//   - PrimaryKey heißt überall `id` (Strings sind ok).
//   - Foreign-Keys snake_case mit `_id`-Suffix.
//   - Model-Class-Name = Singular (Service, nicht Services).
//   - `entity` (statisches Feld) = Tabellenname (snake_case Plural).

import { Model } from 'pinia-orm'

// ---------- Service-Inventar (für ServiceMap, KPI-Strip) -----------------

export class Service extends Model {
  static entity = 'services'

  static fields() {
    return {
      id: this.string(''),
      name: this.string(''),
      status: this.string('unknown'),
      category: this.string('optional'),
      port: this.number(0).nullable(),
      uptime: this.number(0),
      backend: this.string(null).nullable(),
      // Relations
      resources: this.hasMany(Resource, 'service_id'),
      tokens: this.hasMany(Token, 'service_id'),
    }
  }

  declare id: string
  declare name: string
  declare status: string
  declare category: string
  declare port: number | null
  declare uptime: number
  declare backend: string | null
  declare resources: Resource[]
  declare tokens: Token[]
}

export class Resource extends Model {
  static entity = 'resources'

  static fields() {
    return {
      id: this.string(''),
      service_id: this.string(''),
      kind: this.string(''), // cpu | memory | gpu | port | volume
      label: this.string(''),
      value: this.string(''),
      service: this.belongsTo(Service, 'service_id'),
    }
  }

  declare id: string
  declare service_id: string
  declare kind: string
  declare label: string
  declare value: string
  declare service: Service | null
}

export class Token extends Model {
  static entity = 'tokens'

  static fields() {
    return {
      id: this.string(''),
      service_id: this.string(''),
      name: this.string(''),
      scope: this.string(''),
      created_at: this.string(''),
      service: this.belongsTo(Service, 'service_id'),
    }
  }

  declare id: string
  declare service_id: string
  declare name: string
  declare scope: string
  declare created_at: string
  declare service: Service | null
}

// ---------- Finance Guru (Strategy / Position / Trade) -------------------

export class Strategy extends Model {
  static entity = 'strategies'

  static fields() {
    return {
      id: this.string(''),
      name: this.string(''),
      kind: this.string(''), // momentum | mean_reversion | news_sentiment …
      enabled: this.boolean(true),
      seeded: this.number(1000),
      equity: this.number(0),
      pnl: this.number(0),
      positions: this.hasMany(Position, 'strategy_id'),
      trades: this.hasMany(Trade, 'strategy_id'),
    }
  }

  declare id: string
  declare name: string
  declare kind: string
  declare enabled: boolean
  declare seeded: number
  declare equity: number
  declare pnl: number
  declare positions: Position[]
  declare trades: Trade[]
}

export class Position extends Model {
  static entity = 'positions'

  static fields() {
    return {
      id: this.string(''),
      strategy_id: this.string(''),
      symbol: this.string(''),
      qty: this.number(0),
      avg_price: this.number(0),
      mark_price: this.number(0),
      unrealised_pnl: this.number(0),
      opened_at: this.string(''),
      strategy: this.belongsTo(Strategy, 'strategy_id'),
    }
  }

  declare id: string
  declare strategy_id: string
  declare symbol: string
  declare qty: number
  declare avg_price: number
  declare mark_price: number
  declare unrealised_pnl: number
  declare opened_at: string
  declare strategy: Strategy | null
}

export class Trade extends Model {
  static entity = 'trades'

  static fields() {
    return {
      id: this.string(''),
      strategy_id: this.string(''),
      position_id: this.string(null).nullable(),
      symbol: this.string(''),
      side: this.string(''), // buy | sell
      qty: this.number(0),
      price: this.number(0),
      pnl: this.number(0),
      reason: this.string(''),
      executed_at: this.string(''),
      strategy: this.belongsTo(Strategy, 'strategy_id'),
      position: this.belongsTo(Position, 'position_id'),
    }
  }

  declare id: string
  declare strategy_id: string
  declare position_id: string | null
  declare symbol: string
  declare side: 'buy' | 'sell'
  declare qty: number
  declare price: number
  declare pnl: number
  declare reason: string
  declare executed_at: string
  declare strategy: Strategy | null
  declare position: Position | null
}

// ---------- Lotto Oracle ------------------------------------------------

export class Game extends Model {
  static entity = 'lotto_games'

  static fields() {
    return {
      id: this.string(''), // 6aus49 | eurojackpot | spiel77 | super6
      name: this.string(''),
      pool: this.string(''),
      days: this.string(''),
      draws: this.hasMany(Draw, 'game_id'),
      tipsets: this.hasMany(TipSet, 'game_id'),
    }
  }

  declare id: string
  declare name: string
  declare pool: string
  declare days: string
  declare draws: Draw[]
  declare tipsets: TipSet[]
}

export class Draw extends Model {
  static entity = 'lotto_draws'

  static fields() {
    return {
      id: this.string(''),
      game_id: this.string(''),
      drawn_at: this.string(''),
      numbers: this.attr<number[]>([]),
      bonus: this.attr<number[] | null>(null).nullable(),
      jackpot: this.number(0),
      game: this.belongsTo(Game, 'game_id'),
    }
  }

  declare id: string
  declare game_id: string
  declare drawn_at: string
  declare numbers: number[]
  declare bonus: number[] | null
  declare jackpot: number
  declare game: Game | null
}

export class TipSet extends Model {
  static entity = 'lotto_tipsets'

  static fields() {
    return {
      id: this.string(''),
      game_id: this.string(''),
      strategy: this.string(''), // recency_exclude | frequency_hot …
      generated_at: this.string(''),
      reference_draw_id: this.string(null).nullable(),
      tips: this.attr<Array<{ numbers: number[], bonus?: number[] }>>([]),
      game: this.belongsTo(Game, 'game_id'),
      reference_draw: this.belongsTo(Draw, 'reference_draw_id'),
    }
  }

  declare id: string
  declare game_id: string
  declare strategy: string
  declare generated_at: string
  declare reference_draw_id: string | null
  declare tips: Array<{ numbers: number[], bonus?: number[] }>
  declare game: Game | null
  declare reference_draw: Draw | null
}

// ---------- Repo → Project Map -------------------------------------------

export class Project extends Model {
  static entity = 'projects'

  static fields() {
    return {
      id: this.string(''),
      name: this.string(''),
      vikunja_id: this.string(null).nullable(),
      repo_entries: this.hasMany(RepoMapEntry, 'project_id'),
    }
  }

  declare id: string
  declare name: string
  declare vikunja_id: string | null
  declare repo_entries: RepoMapEntry[]
}

export class Workflow extends Model {
  static entity = 'workflows'

  static fields() {
    return {
      id: this.string(''),
      n8n_id: this.string(''),
      name: this.string(''),
      active: this.boolean(false),
      repo_entry_id: this.string(null).nullable(),
      repo_entry: this.belongsTo(RepoMapEntry, 'repo_entry_id'),
    }
  }

  declare id: string
  declare n8n_id: string
  declare name: string
  declare active: boolean
  declare repo_entry_id: string | null
  declare repo_entry: RepoMapEntry | null
}

export class RepoMapEntry extends Model {
  static entity = 'repo_map_entries'

  static fields() {
    return {
      id: this.string(''),
      repo: this.string(''),
      branch: this.string(''),
      project_id: this.string(null).nullable(),
      last_sync: this.string(''),
      project: this.belongsTo(Project, 'project_id'),
      workflows: this.hasMany(Workflow, 'repo_entry_id'),
    }
  }

  declare id: string
  declare repo: string
  declare branch: string
  declare project_id: string | null
  declare last_sync: string
  declare project: Project | null
  declare workflows: Workflow[]
}

