import React, { useState } from 'react';

export const ContactUs: React.FC = () => {
  const [formData, setFormData] = useState({ name: '', email: '', message: '' });
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitted(true);
    setTimeout(() => setSubmitted(false), 3000);
    setFormData({ name: '', email: '', message: '' });
  };

  return (
    <div className="container" style={{ paddingTop: 'var(--spacing-3xl)', paddingBottom: 'var(--spacing-3xl)' }}>
      <h1>Contact Us</h1>

      <div className="grid grid-2" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <div>
          <h3>Get in Touch</h3>
          <p>Have questions? We'd love to hear from you.</p>

          <div style={{ marginTop: 'var(--spacing-2xl)' }}>
            <div style={{ marginBottom: 'var(--spacing-lg)' }}>
              <h5>Email</h5>
              <a href="mailto:info@stocklist.com">info@stocklist.com</a>
            </div>
            <div style={{ marginBottom: 'var(--spacing-lg)' }}>
              <h5>Phone</h5>
              <a href="tel:+15551234567">+1 (555) 123-4567</a>
            </div>
            <div>
              <h5>Address</h5>
              <p>123 Finance Street<br />New York, NY 10001<br />United States</p>
            </div>
          </div>
        </div>

        <div className="card">
          {submitted && (
            <div className="alert alert-success" style={{ marginBottom: 'var(--spacing-lg)' }}>
              ✓ Message sent successfully!
            </div>
          )}

          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label className="form-label required">Name</label>
              <input
                type="text"
                className="form-input"
                placeholder="Your name"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label required">Email</label>
              <input
                type="email"
                className="form-input"
                placeholder="your@email.com"
                value={formData.email}
                onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label required">Message</label>
              <textarea
                className="form-textarea"
                placeholder="Your message..."
                value={formData.message}
                onChange={(e) => setFormData({ ...formData, message: e.target.value })}
                required
              ></textarea>
            </div>

            <button type="submit" className="btn btn-primary" style={{ width: '100%' }}>
              Send Message
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};