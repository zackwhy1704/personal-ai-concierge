'use client'
import { useEffect, useState } from 'react'
import { api } from '@/lib/api'

const CATEGORIES = ['room_upgrades', 'wellness', 'dining', 'transport', 'activities', 'packages']
const CURRENCIES = ['USD', 'EUR', 'GBP', 'SGD', 'MYR']

const categoryColors: Record<string, string> = {
  room_upgrades: 'bg-blue-100 text-blue-700',
  wellness: 'bg-green-100 text-green-700',
  dining: 'bg-orange-100 text-orange-700',
  transport: 'bg-purple-100 text-purple-700',
  activities: 'bg-pink-100 text-pink-700',
  packages: 'bg-indigo-100 text-indigo-700',
}

interface ProductForm {
  name: string
  description: string
  category: string
  price: string
  currency: string
  action_url: string
  tags: string[]
}

const emptyForm: ProductForm = {
  name: '', description: '', category: '', price: '',
  currency: 'USD', action_url: '', tags: [''],
}

export default function ProductsPage() {
  const [products, setProducts] = useState<Array<Record<string, unknown>>>([])
  const [showForm, setShowForm] = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<ProductForm>({ ...emptyForm })
  const [saving, setSaving] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<Array<Record<string, unknown>> | null>(null)
  const [importJson, setImportJson] = useState('')

  useEffect(() => { loadProducts() }, [])

  async function loadProducts() {
    try {
      const data = await api.listProducts()
      setProducts(data)
    } catch (err) {
      console.error(err)
    }
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    try {
      const payload: Record<string, unknown> = {
        name: form.name,
        description: form.description,
        category: form.category,
        price: parseFloat(form.price) || 0,
        currency: form.currency,
        action_url: form.action_url || undefined,
        tags: form.tags.filter(t => t.trim()),
      }
      if (editingId) {
        await api.updateProduct(editingId, payload)
      } else {
        await api.createProduct(payload)
      }
      setShowForm(false)
      setEditingId(null)
      setForm({ ...emptyForm })
      loadProducts()
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to save product')
    } finally {
      setSaving(false)
    }
  }

  function handleEdit(product: Record<string, unknown>) {
    setForm({
      name: String(product.name || ''),
      description: String(product.description || ''),
      category: String(product.category || ''),
      price: String(product.price || ''),
      currency: String(product.currency || 'USD'),
      action_url: String(product.action_url || ''),
      tags: (product.tags as string[] || []).length > 0 ? product.tags as string[] : [''],
    })
    setEditingId(String(product.id))
    setShowForm(true)
  }

  async function handleDelete(id: string) {
    if (!confirm('Delete this product?')) return
    await api.deleteProduct(id)
    loadProducts()
  }

  async function handleSearch() {
    if (!searchQuery.trim()) return
    try {
      const result = await api.searchProducts(searchQuery)
      setSearchResults((result as Record<string, unknown>).results as Array<Record<string, unknown>> || [])
    } catch (err) {
      console.error(err)
    }
  }

  async function handleImport() {
    try {
      const data = JSON.parse(importJson)
      const items = Array.isArray(data) ? data : [data]
      const result = await api.importProducts(items) as Record<string, unknown>
      alert(`Imported ${result.imported} products`)
      setShowImport(false)
      setImportJson('')
      loadProducts()
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Import failed. Check JSON format.')
    }
  }

  return (
    <div className="max-w-4xl">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold text-gray-800">Product Catalog</h1>
        <div className="flex gap-2">
          <button onClick={() => { setShowImport(!showImport); setShowForm(false) }}
            className="px-4 py-2 bg-gray-600 text-white rounded-lg text-sm hover:bg-gray-700">
            {showImport ? 'Cancel' : 'Import'}
          </button>
          <button onClick={() => {
            setShowForm(!showForm); setShowImport(false)
            if (showForm) { setEditingId(null); setForm({ ...emptyForm }) }
          }}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700">
            {showForm ? 'Cancel' : '+ Add Product'}
          </button>
        </div>
      </div>

      {/* Search */}
      <div className="p-6 bg-white rounded-xl shadow-sm border mb-6">
        <h3 className="font-semibold text-gray-700 mb-3">Search Products</h3>
        <div className="flex gap-2">
          <input value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
            placeholder="Search by description, e.g. 'relaxing spa treatment'..."
            className="flex-1 px-3 py-2 border rounded-lg text-sm"
            onKeyDown={e => e.key === 'Enter' && handleSearch()} />
          <button onClick={handleSearch}
            className="px-4 py-2 bg-gray-800 text-white rounded-lg text-sm hover:bg-gray-900">Search</button>
        </div>
        {searchResults && (
          <div className="mt-3 space-y-2">
            {searchResults.length > 0 ? searchResults.map((r, i) => (
              <div key={i} className="p-3 bg-gray-50 rounded-lg text-sm">
                <div className="flex justify-between">
                  <span className="font-medium">{String(r.name || r.title || '')}</span>
                  <span className="text-gray-400">{(Number(r.score) * 100).toFixed(0)}% match</span>
                </div>
                <p className="text-gray-500 text-xs mt-1">{String(r.content || r.description || '').slice(0, 150)}</p>
              </div>
            )) : <p className="text-gray-500 text-sm mt-2">No results found</p>}
          </div>
        )}
      </div>

      {/* Import */}
      {showImport && (
        <div className="p-6 bg-white rounded-xl shadow-sm border mb-6">
          <h3 className="font-semibold text-gray-700 mb-3">Bulk Import (JSON)</h3>
          <textarea value={importJson} onChange={e => setImportJson(e.target.value)}
            placeholder={'[\n  { "name": "Product", "description": "...", "category": "wellness", "price": 99.00, "tags": ["spa"] }\n]'}
            className="w-full px-3 py-2 border rounded-lg text-sm font-mono h-32" />
          <button onClick={handleImport}
            className="mt-2 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700">Import Products</button>
        </div>
      )}

      {/* Create/Edit Form */}
      {showForm && (
        <form onSubmit={handleSave} className="p-6 bg-white rounded-xl shadow-sm border mb-6">
          <h3 className="font-semibold text-gray-700 mb-4">{editingId ? 'Edit Product' : 'New Product'}</h3>
          <div className="space-y-3">
            <input value={form.name} onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
              placeholder="Product name" className="w-full px-3 py-2 border rounded-lg text-sm" required />
            <textarea value={form.description} onChange={e => setForm(p => ({ ...p, description: e.target.value }))}
              placeholder="Description (used for semantic matching — be descriptive)"
              className="w-full px-3 py-2 border rounded-lg text-sm h-24" />
            <div className="grid grid-cols-3 gap-3">
              <select value={form.category} onChange={e => setForm(p => ({ ...p, category: e.target.value }))}
                className="px-3 py-2 border rounded-lg text-sm bg-white">
                <option value="">Category...</option>
                {CATEGORIES.map(c => <option key={c} value={c}>{c.replace('_', ' ')}</option>)}
              </select>
              <input type="number" step="0.01" value={form.price}
                onChange={e => setForm(p => ({ ...p, price: e.target.value }))}
                placeholder="Price" className="px-3 py-2 border rounded-lg text-sm" />
              <select value={form.currency} onChange={e => setForm(p => ({ ...p, currency: e.target.value }))}
                className="px-3 py-2 border rounded-lg text-sm bg-white">
                {CURRENCIES.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <input value={form.action_url} onChange={e => setForm(p => ({ ...p, action_url: e.target.value }))}
              placeholder="Action URL (booking link)" className="w-full px-3 py-2 border rounded-lg text-sm" />

            <div>
              <label className="text-xs font-medium text-gray-600">Tags:</label>
              {form.tags.map((tag, i) => (
                <div key={i} className="flex gap-2 mt-1">
                  <input value={tag}
                    onChange={e => {
                      const u = [...form.tags]; u[i] = e.target.value
                      setForm(p => ({ ...p, tags: u }))
                    }}
                    placeholder={`Tag ${i + 1}`}
                    className="flex-1 px-3 py-2 border rounded-lg text-sm" />
                  {form.tags.length > 1 && (
                    <button type="button" onClick={() => setForm(p => ({ ...p, tags: p.tags.filter((_, j) => j !== i) }))}
                      className="text-red-400 hover:text-red-600 text-sm px-2">X</button>
                  )}
                </div>
              ))}
              <button type="button" onClick={() => setForm(p => ({ ...p, tags: [...p.tags, ''] }))}
                className="text-xs text-blue-600 mt-1">+ Add tag</button>
            </div>

            <button type="submit" disabled={saving}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50">
              {saving ? 'Saving...' : editingId ? 'Update Product' : 'Create Product'}
            </button>
          </div>
        </form>
      )}

      {/* Product List */}
      <div className="space-y-3">
        {products.map(product => (
          <div key={String(product.id)} className="p-4 bg-white rounded-xl shadow-sm border">
            <div className="flex justify-between items-start">
              <div className="flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <h4 className="font-medium text-gray-800">{String(product.name)}</h4>
                  {String(product.category || '') !== '' && (
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${categoryColors[String(product.category)] || 'bg-gray-100 text-gray-700'}`}>
                      {String(product.category).replace('_', ' ')}
                    </span>
                  )}
                  {Number(product.price || 0) > 0 && (
                    <span className="text-sm font-semibold text-green-700">
                      {String(product.currency || 'USD')} {Number(product.price).toFixed(2)}
                    </span>
                  )}
                </div>
                {String(product.description || '') !== '' && (
                  <p className="text-xs text-gray-500 mt-1">{String(product.description).slice(0, 120)}{String(product.description).length > 120 ? '...' : ''}</p>
                )}
                {(product.tags as string[] || []).length > 0 && (
                  <div className="flex gap-1 mt-2 flex-wrap">
                    {(product.tags as string[]).map((tag, i) => (
                      <span key={i} className="px-2 py-0.5 bg-gray-100 rounded text-xs text-gray-600">{tag}</span>
                    ))}
                  </div>
                )}
              </div>
              <div className="flex gap-2 ml-4">
                <button onClick={() => handleEdit(product)}
                  className="text-blue-500 hover:text-blue-700 text-sm">Edit</button>
                <button onClick={() => handleDelete(String(product.id))}
                  className="text-red-400 hover:text-red-600 text-sm">Delete</button>
              </div>
            </div>
          </div>
        ))}
        {products.length === 0 && (
          <p className="text-gray-500 text-center py-8">No products yet. Add products for the bot to recommend.</p>
        )}
      </div>
    </div>
  )
}
