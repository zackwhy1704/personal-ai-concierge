'use client'
import { useEffect, useState } from 'react'
import { api } from '@/lib/api'

const TRIGGER_TYPES = [
  { value: 'keyword', label: 'Keyword Match' },
  { value: 'intent_match', label: 'Intent Match' },
  { value: 'category_context', label: 'Category Context' },
  { value: 'proactive', label: 'Proactive' },
  { value: 'cross_sell', label: 'Cross-Sell' },
]

const triggerColors: Record<string, string> = {
  keyword: 'bg-blue-100 text-blue-700',
  intent_match: 'bg-purple-100 text-purple-700',
  category_context: 'bg-green-100 text-green-700',
  proactive: 'bg-yellow-100 text-yellow-700',
  cross_sell: 'bg-orange-100 text-orange-700',
}

interface StrategyForm {
  name: string
  description: string
  trigger_type: string
  keywords: string
  intent_name: string
  category: string
  probability: string
  cross_sell_pairs: Array<{ if_category: string; suggest_category: string }>
  prompt_template: string
  max_attempts_per_session: string
  priority: string
}

const emptyForm: StrategyForm = {
  name: '', description: '', trigger_type: 'keyword',
  keywords: '', intent_name: '', category: '', probability: '0.3',
  cross_sell_pairs: [{ if_category: '', suggest_category: '' }],
  prompt_template: '', max_attempts_per_session: '2', priority: '5',
}

export default function StrategiesPage() {
  const [strategies, setStrategies] = useState<Array<Record<string, unknown>>>([])
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<StrategyForm>({ ...emptyForm })
  const [saving, setSaving] = useState(false)
  const [testMsg, setTestMsg] = useState('')
  const [testResult, setTestResult] = useState<Record<string, unknown> | null>(null)

  useEffect(() => { loadStrategies() }, [])

  async function loadStrategies() {
    try {
      const data = await api.listStrategies()
      setStrategies(data)
    } catch (err) {
      console.error(err)
    }
  }

  function buildTriggerConfig(): Record<string, unknown> {
    switch (form.trigger_type) {
      case 'keyword':
        return { keywords: form.keywords.split(',').map(k => k.trim()).filter(Boolean) }
      case 'intent_match':
        return { intent_names: form.intent_name.split(',').map(k => k.trim()).filter(Boolean) }
      case 'category_context':
        return { categories: form.category.split(',').map(k => k.trim()).filter(Boolean) }
      case 'proactive':
        return { probability: parseFloat(form.probability) || 0.3 }
      case 'cross_sell':
        return { product_pairs: form.cross_sell_pairs.filter(p => p.if_category && p.suggest_category) }
      default:
        return {}
    }
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    try {
      const payload: Record<string, unknown> = {
        name: form.name,
        description: form.description,
        trigger_type: form.trigger_type,
        trigger_config: buildTriggerConfig(),
        prompt_template: form.prompt_template,
        max_attempts_per_session: parseInt(form.max_attempts_per_session) || 2,
        priority: parseInt(form.priority) || 5,
      }
      if (editingId) {
        await api.updateStrategy(editingId, payload)
      } else {
        await api.createStrategy(payload)
      }
      setShowForm(false)
      setEditingId(null)
      setForm({ ...emptyForm })
      loadStrategies()
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to save strategy')
    } finally {
      setSaving(false)
    }
  }

  function handleEdit(strategy: Record<string, unknown>) {
    const config = (strategy.trigger_config || {}) as Record<string, unknown>
    const triggerType = String(strategy.trigger_type || 'keyword')
    setForm({
      name: String(strategy.name || ''),
      description: String(strategy.description || ''),
      trigger_type: triggerType,
      keywords: triggerType === 'keyword' ? ((config.keywords as string[]) || []).join(', ') : '',
      intent_name: triggerType === 'intent_match' ? ((config.intent_names as string[]) || []).join(', ') : '',
      category: triggerType === 'category_context' ? ((config.categories as string[]) || []).join(', ') : '',
      probability: triggerType === 'proactive' ? String(config.probability || '0.3') : '0.3',
      cross_sell_pairs: triggerType === 'cross_sell' && (config.product_pairs as Array<{ if_category: string; suggest_category: string }>)?.length
        ? config.product_pairs as Array<{ if_category: string; suggest_category: string }>
        : [{ if_category: '', suggest_category: '' }],
      prompt_template: String(strategy.prompt_template || ''),
      max_attempts_per_session: String(strategy.max_attempts_per_session || '2'),
      priority: String(strategy.priority || '5'),
    })
    setEditingId(String(strategy.id))
    setShowForm(true)
  }

  async function handleDelete(id: string) {
    if (!confirm('Delete this strategy?')) return
    await api.deleteStrategy(id)
    loadStrategies()
  }

  async function handleToggle(id: string) {
    try {
      await api.toggleStrategy(id)
      loadStrategies()
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to toggle strategy')
    }
  }

  async function handleTest() {
    if (!testMsg.trim()) return
    try {
      const result = await api.testStrategies(testMsg)
      setTestResult(result as Record<string, unknown>)
    } catch (err) {
      console.error(err)
    }
  }

  return (
    <div className="max-w-4xl">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold text-gray-800">Upsell Strategies</h1>
        <button onClick={() => {
          setShowForm(!showForm)
          if (showForm) { setEditingId(null); setForm({ ...emptyForm }) }
        }}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700">
          {showForm ? 'Cancel' : '+ New Strategy'}
        </button>
      </div>

      {/* Test */}
      <div className="p-6 bg-white rounded-xl shadow-sm border mb-6">
        <h3 className="font-semibold text-gray-700 mb-3">Test Strategy Matching</h3>
        <div className="flex gap-2">
          <input value={testMsg} onChange={e => setTestMsg(e.target.value)}
            placeholder="Type a guest message to test which strategies fire..."
            className="flex-1 px-3 py-2 border rounded-lg text-sm"
            onKeyDown={e => e.key === 'Enter' && handleTest()} />
          <button onClick={handleTest}
            className="px-4 py-2 bg-gray-800 text-white rounded-lg text-sm hover:bg-gray-900">Test</button>
        </div>
        {testResult && (
          <div className="mt-3 p-3 bg-gray-50 rounded-lg text-sm">
            {(testResult.matched_strategies as Array<Record<string, unknown>>)?.length > 0 ? (
              <div className="space-y-1">
                <p className="font-medium text-gray-700 mb-2">Matched Strategies:</p>
                {(testResult.matched_strategies as Array<Record<string, unknown>>).map((s, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${triggerColors[String(s.trigger_type)] || 'bg-gray-100'}`}>
                      {String(s.trigger_type)}
                    </span>
                    <span>{String(s.name)}</span>
                    <span className="text-gray-400 text-xs">priority: {String(s.priority)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-gray-500">No strategies matched this message</p>
            )}
          </div>
        )}
      </div>

      {/* Create/Edit Form */}
      {showForm && (
        <form onSubmit={handleSave} className="p-6 bg-white rounded-xl shadow-sm border mb-6">
          <h3 className="font-semibold text-gray-700 mb-4">{editingId ? 'Edit Strategy' : 'New Strategy'}</h3>
          <div className="space-y-3">
            <input value={form.name} onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
              placeholder="Strategy name (e.g., Wellness Upsell)" className="w-full px-3 py-2 border rounded-lg text-sm" required />
            <input value={form.description} onChange={e => setForm(p => ({ ...p, description: e.target.value }))}
              placeholder="Description" className="w-full px-3 py-2 border rounded-lg text-sm" />

            <div className="grid grid-cols-3 gap-3">
              <select value={form.trigger_type} onChange={e => setForm(p => ({ ...p, trigger_type: e.target.value }))}
                className="px-3 py-2 border rounded-lg text-sm bg-white">
                {TRIGGER_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
              <input type="number" value={form.max_attempts_per_session}
                onChange={e => setForm(p => ({ ...p, max_attempts_per_session: e.target.value }))}
                placeholder="Max attempts/session" className="px-3 py-2 border rounded-lg text-sm" min="1" max="10" />
              <input type="number" value={form.priority}
                onChange={e => setForm(p => ({ ...p, priority: e.target.value }))}
                placeholder="Priority (1-20)" className="px-3 py-2 border rounded-lg text-sm" min="1" max="20" />
            </div>

            {/* Trigger Config (conditional) */}
            <div className="p-3 bg-gray-50 rounded-lg">
              <label className="text-xs font-medium text-gray-600 block mb-2">
                Trigger Configuration ({TRIGGER_TYPES.find(t => t.value === form.trigger_type)?.label})
              </label>
              {form.trigger_type === 'keyword' && (
                <textarea value={form.keywords}
                  onChange={e => setForm(p => ({ ...p, keywords: e.target.value }))}
                  placeholder="tired, exhausted, stressed, relax, spa, massage (comma-separated)"
                  className="w-full px-3 py-2 border rounded-lg text-sm h-20" />
              )}
              {form.trigger_type === 'intent_match' && (
                <input value={form.intent_name}
                  onChange={e => setForm(p => ({ ...p, intent_name: e.target.value }))}
                  placeholder="Intent names (comma-separated, e.g., room_booking, spa_booking)"
                  className="w-full px-3 py-2 border rounded-lg text-sm" />
              )}
              {form.trigger_type === 'category_context' && (
                <input value={form.category}
                  onChange={e => setForm(p => ({ ...p, category: e.target.value }))}
                  placeholder="Categories (comma-separated, e.g., wellness, dining)"
                  className="w-full px-3 py-2 border rounded-lg text-sm" />
              )}
              {form.trigger_type === 'proactive' && (
                <div>
                  <input type="number" step="0.05" min="0" max="1" value={form.probability}
                    onChange={e => setForm(p => ({ ...p, probability: e.target.value }))}
                    className="w-full px-3 py-2 border rounded-lg text-sm" />
                  <p className="text-xs text-gray-400 mt-1">Probability of triggering (0.0 - 1.0). 0.3 = 30% chance.</p>
                </div>
              )}
              {form.trigger_type === 'cross_sell' && (
                <div className="space-y-2">
                  {form.cross_sell_pairs.map((pair, i) => (
                    <div key={i} className="flex gap-2 items-center">
                      <input value={pair.if_category}
                        onChange={e => {
                          const u = [...form.cross_sell_pairs]; u[i] = { ...u[i], if_category: e.target.value }
                          setForm(p => ({ ...p, cross_sell_pairs: u }))
                        }}
                        placeholder="If category (e.g., wellness)"
                        className="flex-1 px-3 py-2 border rounded-lg text-sm" />
                      <span className="text-gray-400 text-sm">→</span>
                      <input value={pair.suggest_category}
                        onChange={e => {
                          const u = [...form.cross_sell_pairs]; u[i] = { ...u[i], suggest_category: e.target.value }
                          setForm(p => ({ ...p, cross_sell_pairs: u }))
                        }}
                        placeholder="Suggest category (e.g., dining)"
                        className="flex-1 px-3 py-2 border rounded-lg text-sm" />
                      {form.cross_sell_pairs.length > 1 && (
                        <button type="button"
                          onClick={() => setForm(p => ({ ...p, cross_sell_pairs: p.cross_sell_pairs.filter((_, j) => j !== i) }))}
                          className="text-red-400 hover:text-red-600 text-sm">X</button>
                      )}
                    </div>
                  ))}
                  <button type="button"
                    onClick={() => setForm(p => ({ ...p, cross_sell_pairs: [...p.cross_sell_pairs, { if_category: '', suggest_category: '' }] }))}
                    className="text-xs text-blue-600">+ Add pair</button>
                </div>
              )}
            </div>

            <div>
              <label className="text-xs font-medium text-gray-600 block mb-1">Prompt Template</label>
              <textarea value={form.prompt_template}
                onChange={e => setForm(p => ({ ...p, prompt_template: e.target.value }))}
                placeholder="Instructions for how the AI should present this upsell. Be specific about tone and approach..."
                className="w-full px-3 py-2 border rounded-lg text-sm h-24" />
              <p className="text-xs text-gray-400 mt-1">This gets injected into the AI system prompt when the strategy fires.</p>
            </div>

            <button type="submit" disabled={saving}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50">
              {saving ? 'Saving...' : editingId ? 'Update Strategy' : 'Create Strategy'}
            </button>
          </div>
        </form>
      )}

      {/* Strategy List */}
      <div className="space-y-3">
        {strategies.map(strategy => (
          <div key={String(strategy.id)} className="p-4 bg-white rounded-xl shadow-sm border">
            <div className="flex justify-between items-start">
              <div className="flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <h4 className="font-medium text-gray-800">{String(strategy.name)}</h4>
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${triggerColors[String(strategy.trigger_type)] || 'bg-gray-100 text-gray-700'}`}>
                    {String(strategy.trigger_type).replace('_', ' ')}
                  </span>
                  <span className="text-xs text-gray-400">Priority: {String(strategy.priority)}</span>
                  <span className="text-xs text-gray-400">Max: {String(strategy.max_attempts_per_session)}/session</span>
                </div>
                {String(strategy.description || '') !== '' && (
                  <p className="text-xs text-gray-500 mt-1">{String(strategy.description)}</p>
                )}
                {String(strategy.prompt_template || '') !== '' && (
                  <p className="text-xs text-gray-400 mt-1 italic">&quot;{String(strategy.prompt_template).slice(0, 100)}...&quot;</p>
                )}
              </div>
              <div className="flex items-center gap-3 ml-4">
                <button onClick={() => handleToggle(String(strategy.id))}
                  className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                    strategy.is_active
                      ? 'bg-green-100 text-green-700 hover:bg-green-200'
                      : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                  }`}>
                  {strategy.is_active ? 'Active' : 'Inactive'}
                </button>
                <button onClick={() => handleEdit(strategy)}
                  className="text-blue-500 hover:text-blue-700 text-sm">Edit</button>
                <button onClick={() => handleDelete(String(strategy.id))}
                  className="text-red-400 hover:text-red-600 text-sm">Delete</button>
              </div>
            </div>
          </div>
        ))}
        {strategies.length === 0 && (
          <p className="text-gray-500 text-center py-8">No upsell strategies configured. Create one to start selling.</p>
        )}
      </div>
    </div>
  )
}
