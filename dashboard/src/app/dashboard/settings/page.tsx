'use client'
import { useEffect, useState } from 'react'
import { api } from '@/lib/api'

export default function SettingsPage() {
  const [tenant, setTenant] = useState<Record<string, unknown> | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [form, setForm] = useState({
    name: '',
    whatsapp_phone_number_id: '',
    whatsapp_business_account_id: '',
    whatsapp_access_token: '',
    admin_phone_numbers: '',
  })

  useEffect(() => {
    async function load() {
      try {
        const data = await api.getMe() as Record<string, unknown>
        setTenant(data)
        setForm({
          name: String(data.name || ''),
          whatsapp_phone_number_id: String(data.whatsapp_phone_number_id || ''),
          whatsapp_business_account_id: '',
          whatsapp_access_token: '',
          admin_phone_numbers: '',
        })
      } catch (err) {
        console.error(err)
      }
    }
    load()
  }, [])

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setSaved(false)
    try {
      const data: Record<string, string> = {}
      if (form.name) data.name = form.name
      if (form.whatsapp_phone_number_id) data.whatsapp_phone_number_id = form.whatsapp_phone_number_id
      if (form.whatsapp_business_account_id) data.whatsapp_business_account_id = form.whatsapp_business_account_id
      if (form.whatsapp_access_token) data.whatsapp_access_token = form.whatsapp_access_token
      if (form.admin_phone_numbers) data.admin_phone_numbers = form.admin_phone_numbers
      await api.updateMe(data)
      setSaved(true)
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  if (!tenant) return <div className="text-gray-500">Loading...</div>

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-bold text-gray-800 mb-6">Settings</h1>

      <form onSubmit={handleSave} className="space-y-6">
        <div className="p-6 bg-white rounded-xl shadow-sm border">
          <h3 className="font-semibold text-gray-700 mb-4">General</h3>
          <div className="mb-3">
            <label className="block text-sm font-medium text-gray-700 mb-1">Business Name</label>
            <input value={form.name} onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
              className="w-full px-3 py-2 border rounded-lg text-sm" />
          </div>
        </div>

        <div className="p-6 bg-white rounded-xl shadow-sm border">
          <h3 className="font-semibold text-gray-700 mb-4">WhatsApp Configuration</h3>
          <div className="space-y-3">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Phone Number ID</label>
              <input value={form.whatsapp_phone_number_id}
                onChange={e => setForm(p => ({ ...p, whatsapp_phone_number_id: e.target.value }))}
                className="w-full px-3 py-2 border rounded-lg text-sm" placeholder="From Meta Business Manager" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Business Account ID</label>
              <input value={form.whatsapp_business_account_id}
                onChange={e => setForm(p => ({ ...p, whatsapp_business_account_id: e.target.value }))}
                className="w-full px-3 py-2 border rounded-lg text-sm" placeholder="From Meta Business Manager" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Access Token</label>
              <input type="password" value={form.whatsapp_access_token}
                onChange={e => setForm(p => ({ ...p, whatsapp_access_token: e.target.value }))}
                className="w-full px-3 py-2 border rounded-lg text-sm" placeholder="Permanent access token" />
              <p className="text-xs text-gray-400 mt-1">Leave blank to keep existing token</p>
            </div>
          </div>
        </div>

        <div className="p-6 bg-white rounded-xl shadow-sm border">
          <h3 className="font-semibold text-gray-700 mb-4">Admin Phone Numbers</h3>
          <input value={form.admin_phone_numbers}
            onChange={e => setForm(p => ({ ...p, admin_phone_numbers: e.target.value }))}
            className="w-full px-3 py-2 border rounded-lg text-sm"
            placeholder="Comma-separated: +65912345678, +65987654321" />
          <p className="text-xs text-gray-400 mt-1">
            These numbers can use admin commands (/usage, /status) in WhatsApp
          </p>
        </div>

        {saved && <div className="p-3 bg-green-50 text-green-700 rounded-lg text-sm">Settings saved successfully!</div>}

        <button type="submit" disabled={saving}
          className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-medium">
          {saving ? 'Saving...' : 'Save Settings'}
        </button>
      </form>
    </div>
  )
}
