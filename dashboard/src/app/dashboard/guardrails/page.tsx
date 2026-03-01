'use client'
import { useState } from 'react'
import { api } from '@/lib/api'

const DEFAULT_TOPICS = [
  'room_booking', 'room_service', 'amenities_inquiry', 'local_attractions',
  'complaints', 'checkout_info', 'transportation', 'dining', 'spa_wellness',
]

const BLOCKED_DEFAULTS = [
  'competitor_pricing', 'political_discussions', 'medical_advice', 'legal_advice',
]

export default function GuardrailsPage() {
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')

  const [form, setForm] = useState({
    tenant_name: '',
    language: ['en'],
    persona: { name: 'AI Concierge', tone: 'warm, professional, concise', greeting: '' },
    allowed_topics: [] as string[],
    blocked_topics: [] as string[],
    response_limits: { max_response_length: 500, max_conversation_turns: 50, session_timeout_minutes: 30 },
    data_handling: { collect_personal_data: false, store_conversation_history: true, retention_days: 90 },
    custom_rules: [''] as string[],
    escalation_rules: [{ trigger: '', action: 'transfer_to_human', contact: '' }],
  })

  const toggleTopic = (list: 'allowed_topics' | 'blocked_topics', topic: string) => {
    setForm(prev => {
      const current = prev[list]
      const updated = current.includes(topic)
        ? current.filter(t => t !== topic)
        : [...current, topic]
      return { ...prev, [list]: updated }
    })
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError('')
    setSaved(false)
    try {
      const data = {
        ...form,
        custom_rules: form.custom_rules.filter(r => r.trim()),
        escalation_rules: form.escalation_rules.filter(r => r.trigger.trim()),
      }
      await api.createGuardrailFromForm(data)
      setSaved(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save guardrails')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-bold text-gray-800 mb-6">Guardrail Configuration</h1>
      <p className="text-gray-500 mb-8">
        Configure your AI concierge&apos;s personality, rules, and boundaries. This form generates a YAML config that controls how your bot behaves.
      </p>

      <form onSubmit={handleSubmit} className="space-y-8">
        {/* Tenant Name */}
        <Section title="Business Info">
          <Input label="Business Name" value={form.tenant_name}
            onChange={v => setForm(p => ({ ...p, tenant_name: v }))} required />
          <Input label="Languages (comma-separated)" value={form.language.join(', ')}
            onChange={v => setForm(p => ({ ...p, language: v.split(',').map(l => l.trim()).filter(Boolean) }))} />
        </Section>

        {/* Persona */}
        <Section title="AI Persona">
          <Input label="Bot Name" value={form.persona.name}
            onChange={v => setForm(p => ({ ...p, persona: { ...p.persona, name: v } }))} />
          <Input label="Tone" value={form.persona.tone} placeholder="e.g., warm, professional, concise"
            onChange={v => setForm(p => ({ ...p, persona: { ...p.persona, tone: v } }))} />
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Greeting Message</label>
            <textarea value={form.persona.greeting}
              onChange={e => setForm(p => ({ ...p, persona: { ...p.persona, greeting: e.target.value } }))}
              className="w-full px-3 py-2 border rounded-lg text-sm" rows={2}
              placeholder="Welcome to Grand Hotel! I'm Sofia, your AI concierge." />
          </div>
        </Section>

        {/* Topics */}
        <Section title="Allowed Topics">
          <p className="text-xs text-gray-500 mb-2">Select topics the bot can assist with:</p>
          <div className="flex flex-wrap gap-2">
            {DEFAULT_TOPICS.map(t => (
              <button key={t} type="button" onClick={() => toggleTopic('allowed_topics', t)}
                className={`px-3 py-1 rounded-full text-sm border transition-colors ${
                  form.allowed_topics.includes(t)
                    ? 'bg-green-100 border-green-300 text-green-700'
                    : 'bg-gray-50 border-gray-200 text-gray-500'
                }`}>
                {t.replace(/_/g, ' ')}
              </button>
            ))}
          </div>
        </Section>

        <Section title="Blocked Topics">
          <p className="text-xs text-gray-500 mb-2">Select topics the bot should never discuss:</p>
          <div className="flex flex-wrap gap-2">
            {BLOCKED_DEFAULTS.map(t => (
              <button key={t} type="button" onClick={() => toggleTopic('blocked_topics', t)}
                className={`px-3 py-1 rounded-full text-sm border transition-colors ${
                  form.blocked_topics.includes(t)
                    ? 'bg-red-100 border-red-300 text-red-700'
                    : 'bg-gray-50 border-gray-200 text-gray-500'
                }`}>
                {t.replace(/_/g, ' ')}
              </button>
            ))}
          </div>
        </Section>

        {/* Response Limits */}
        <Section title="Response Limits">
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Max Response Length</label>
              <input type="number" value={form.response_limits.max_response_length}
                onChange={e => setForm(p => ({ ...p, response_limits: { ...p.response_limits, max_response_length: Number(e.target.value) } }))}
                className="w-full px-3 py-2 border rounded-lg text-sm" min={100} max={2000} />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Max Turns</label>
              <input type="number" value={form.response_limits.max_conversation_turns}
                onChange={e => setForm(p => ({ ...p, response_limits: { ...p.response_limits, max_conversation_turns: Number(e.target.value) } }))}
                className="w-full px-3 py-2 border rounded-lg text-sm" min={5} max={100} />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Session Timeout (min)</label>
              <input type="number" value={form.response_limits.session_timeout_minutes}
                onChange={e => setForm(p => ({ ...p, response_limits: { ...p.response_limits, session_timeout_minutes: Number(e.target.value) } }))}
                className="w-full px-3 py-2 border rounded-lg text-sm" min={5} max={120} />
            </div>
          </div>
        </Section>

        {/* Custom Rules */}
        <Section title="Custom Rules">
          <p className="text-xs text-gray-500 mb-2">Add specific rules for your concierge to follow:</p>
          {form.custom_rules.map((rule, i) => (
            <div key={i} className="flex gap-2 mb-2">
              <input value={rule}
                onChange={e => {
                  const updated = [...form.custom_rules]
                  updated[i] = e.target.value
                  setForm(p => ({ ...p, custom_rules: updated }))
                }}
                className="flex-1 px-3 py-2 border rounded-lg text-sm"
                placeholder="e.g., Never quote exact room prices; direct to booking link" />
              <button type="button"
                onClick={() => setForm(p => ({ ...p, custom_rules: p.custom_rules.filter((_, j) => j !== i) }))}
                className="text-red-400 hover:text-red-600 px-2">X</button>
            </div>
          ))}
          <button type="button"
            onClick={() => setForm(p => ({ ...p, custom_rules: [...p.custom_rules, ''] }))}
            className="text-sm text-blue-600 hover:text-blue-700">+ Add rule</button>
        </Section>

        {/* Escalation */}
        <Section title="Escalation Rules">
          {form.escalation_rules.map((rule, i) => (
            <div key={i} className="grid grid-cols-3 gap-2 mb-2">
              <input value={rule.trigger}
                onChange={e => {
                  const updated = [...form.escalation_rules]
                  updated[i] = { ...updated[i], trigger: e.target.value }
                  setForm(p => ({ ...p, escalation_rules: updated }))
                }}
                className="px-3 py-2 border rounded-lg text-sm" placeholder="Trigger phrase" />
              <select value={rule.action}
                onChange={e => {
                  const updated = [...form.escalation_rules]
                  updated[i] = { ...updated[i], action: e.target.value }
                  setForm(p => ({ ...p, escalation_rules: updated }))
                }}
                className="px-3 py-2 border rounded-lg text-sm bg-white">
                <option value="transfer_to_human">Transfer to Human</option>
                <option value="log_and_escalate">Log & Escalate</option>
                <option value="auto_respond">Auto Respond</option>
              </select>
              <input value={rule.contact}
                onChange={e => {
                  const updated = [...form.escalation_rules]
                  updated[i] = { ...updated[i], contact: e.target.value }
                  setForm(p => ({ ...p, escalation_rules: updated }))
                }}
                className="px-3 py-2 border rounded-lg text-sm" placeholder="Contact (phone/email)" />
            </div>
          ))}
          <button type="button"
            onClick={() => setForm(p => ({ ...p, escalation_rules: [...p.escalation_rules, { trigger: '', action: 'transfer_to_human', contact: '' }] }))}
            className="text-sm text-blue-600 hover:text-blue-700">+ Add escalation rule</button>
        </Section>

        {error && <div className="p-3 bg-red-50 text-red-700 rounded-lg text-sm">{error}</div>}
        {saved && <div className="p-3 bg-green-50 text-green-700 rounded-lg text-sm">Guardrails saved successfully!</div>}

        <button type="submit" disabled={saving}
          className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-medium">
          {saving ? 'Saving...' : 'Save Guardrails'}
        </button>
      </form>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="p-6 bg-white rounded-xl shadow-sm border">
      <h3 className="text-md font-semibold text-gray-700 mb-4">{title}</h3>
      {children}
    </div>
  )
}

function Input({ label, value, onChange, placeholder, required }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string; required?: boolean
}) {
  return (
    <div className="mb-3">
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      <input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
        className="w-full px-3 py-2 border rounded-lg text-sm" required={required} />
    </div>
  )
}
