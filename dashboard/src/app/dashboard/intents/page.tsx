'use client'
import { useEffect, useState } from 'react'
import { api } from '@/lib/api'

export default function IntentsPage() {
  const [intents, setIntents] = useState<Array<Record<string, unknown>>>([])
  const [showForm, setShowForm] = useState(false)
  const [testMsg, setTestMsg] = useState('')
  const [testResult, setTestResult] = useState<Record<string, unknown> | null>(null)
  const [form, setForm] = useState({
    name: '', description: '', examples: ['', ''],
    action_type: 'link', action_config: { url: '', label: '' },
  })

  useEffect(() => { loadIntents() }, [])

  async function loadIntents() {
    try {
      const data = await api.listIntents()
      setIntents(data)
    } catch (err) {
      console.error(err)
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    try {
      await api.createIntent({
        ...form,
        examples: form.examples.filter(ex => ex.trim()),
      })
      setShowForm(false)
      setForm({ name: '', description: '', examples: ['', ''], action_type: 'link', action_config: { url: '', label: '' } })
      loadIntents()
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to create intent')
    }
  }

  async function handleDelete(id: string) {
    if (!confirm('Delete this intent?')) return
    await api.deleteIntent(id)
    loadIntents()
  }

  async function handleTest() {
    if (!testMsg.trim()) return
    try {
      const result = await api.testIntent(testMsg)
      setTestResult(result as Record<string, unknown>)
    } catch (err) {
      console.error(err)
    }
  }

  return (
    <div className="max-w-4xl">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold text-gray-800">Intent Management</h1>
        <button onClick={() => setShowForm(!showForm)}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700">
          {showForm ? 'Cancel' : '+ New Intent'}
        </button>
      </div>

      {/* Test Intent */}
      <div className="p-6 bg-white rounded-xl shadow-sm border mb-6">
        <h3 className="font-semibold text-gray-700 mb-3">Test Intent Detection</h3>
        <div className="flex gap-2">
          <input value={testMsg} onChange={e => setTestMsg(e.target.value)}
            placeholder="Type a message to test intent detection..."
            className="flex-1 px-3 py-2 border rounded-lg text-sm" />
          <button onClick={handleTest}
            className="px-4 py-2 bg-gray-800 text-white rounded-lg text-sm hover:bg-gray-900">Test</button>
        </div>
        {testResult && (
          <div className="mt-3 p-3 bg-gray-50 rounded-lg text-sm">
            {testResult.intent_name ? (
              <>
                <p>Intent: <strong>{String(testResult.intent_name)}</strong></p>
                <p>Confidence: {(Number(testResult.confidence) * 100).toFixed(1)}%</p>
                <p>Action: {String(testResult.action_type)}</p>
                <p>Matched: &quot;{String(testResult.matched_example)}&quot;</p>
              </>
            ) : (
              <p className="text-gray-500">No intent detected</p>
            )}
          </div>
        )}
      </div>

      {/* Create Form */}
      {showForm && (
        <form onSubmit={handleCreate} className="p-6 bg-white rounded-xl shadow-sm border mb-6">
          <h3 className="font-semibold text-gray-700 mb-4">New Intent</h3>
          <div className="space-y-3">
            <input value={form.name} onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
              placeholder="Intent name (e.g., room_booking)" className="w-full px-3 py-2 border rounded-lg text-sm" required />
            <input value={form.description} onChange={e => setForm(p => ({ ...p, description: e.target.value }))}
              placeholder="Description" className="w-full px-3 py-2 border rounded-lg text-sm" />

            <div>
              <label className="text-xs font-medium text-gray-600">Example Utterances (min 2):</label>
              {form.examples.map((ex, i) => (
                <input key={i} value={ex}
                  onChange={e => {
                    const u = [...form.examples]; u[i] = e.target.value
                    setForm(p => ({ ...p, examples: u }))
                  }}
                  placeholder={`Example ${i + 1}`}
                  className="w-full px-3 py-2 border rounded-lg text-sm mt-1" />
              ))}
              <button type="button" onClick={() => setForm(p => ({ ...p, examples: [...p.examples, ''] }))}
                className="text-xs text-blue-600 mt-1">+ Add example</button>
            </div>

            <select value={form.action_type} onChange={e => setForm(p => ({ ...p, action_type: e.target.value }))}
              className="w-full px-3 py-2 border rounded-lg text-sm bg-white">
              <option value="link">Link (redirect user)</option>
              <option value="api_call">API Call</option>
              <option value="rag_answer">RAG Answer</option>
            </select>

            {form.action_type === 'link' && (
              <div className="grid grid-cols-2 gap-2">
                <input value={form.action_config.url}
                  onChange={e => setForm(p => ({ ...p, action_config: { ...p.action_config, url: e.target.value } }))}
                  placeholder="URL" className="px-3 py-2 border rounded-lg text-sm" />
                <input value={form.action_config.label}
                  onChange={e => setForm(p => ({ ...p, action_config: { ...p.action_config, label: e.target.value } }))}
                  placeholder="Button Label" className="px-3 py-2 border rounded-lg text-sm" />
              </div>
            )}

            <button type="submit"
              className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700">Create Intent</button>
          </div>
        </form>
      )}

      {/* Intent List */}
      <div className="space-y-3">
        {intents.map(intent => (
          <div key={String(intent.id)} className="p-4 bg-white rounded-xl shadow-sm border flex justify-between items-start">
            <div>
              <h4 className="font-medium text-gray-800">{String(intent.name)}</h4>
              <p className="text-xs text-gray-500 mt-1">{String(intent.description)}</p>
              <p className="text-xs text-gray-400 mt-1">
                Action: {String(intent.action_type)} | Examples: {(intent.examples as string[]).length}
              </p>
            </div>
            <button onClick={() => handleDelete(String(intent.id))}
              className="text-red-400 hover:text-red-600 text-sm">Delete</button>
          </div>
        ))}
        {intents.length === 0 && (
          <p className="text-gray-500 text-center py-8">No intents configured yet. Create one to get started.</p>
        )}
      </div>
    </div>
  )
}
