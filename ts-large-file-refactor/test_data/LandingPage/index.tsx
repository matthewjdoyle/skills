import React, { useState } from 'react';
import { LandingPageProps } from './LandingPage.types';
import { EMAIL_REGEX } from './LandingPage.constants';
import { LANDING_PAGE_CONTENT } from './LandingPage.content';

const validateEmail = (email: string) => EMAIL_REGEX.test(email);
const formatPrice = (price: number) => `$${price.toFixed(2)}`;

export const LandingPage: React.FC<LandingPageProps> = ({ user, plans }) => {
  const [email, setEmail] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');
  
  const content = LANDING_PAGE_CONTENT;

  const handleSubscribe = async () => {
    if (!validateEmail(email)) {
      setError("Please enter a valid email address.");
      return;
    }
    
    setIsSubmitting(true);
    setError('');
    
    try {
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 1000));
      alert("Thanks for subscribing!");
      setEmail('');
    } catch (err) {
      setError("An error occurred. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="landing-page">
      {/* Header Section */}
      <header className="header">
        <div className="logo">{content.nav.logo}</div>
        <nav>
          <ul>
            {content.nav.links.map(link => (
              <li key={link.href}><a href={link.href}>{link.label}</a></li>
            ))}
            {user ? (
              <li><a href="#dashboard">{content.nav.auth.dashboard}</a></li>
            ) : (
              <li><a href="#login">{content.nav.auth.login}</a></li>
            )}
          </ul>
        </nav>
      </header>

      {/* Hero Section */}
      <section className="hero">
        <div className="hero-content">
          <h1>{content.hero.title}</h1>
          <p>{content.hero.subtitle}</p>
          <div className="cta-form">
            <input 
              type="email" 
              placeholder="Enter your email address" 
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <button onClick={handleSubscribe} disabled={isSubmitting}>
              {isSubmitting ? "Submitting..." : content.hero.ctaButton}
            </button>
            {error && <p className="error">{error}</p>}
          </div>
        </div>
        <div className="hero-image">
          <img src={content.hero.image.url} alt={content.hero.image.alt} />
        </div>
      </section>

      {/* Features Section */}
      <section id="features" className="features">
        <h2>{content.features.title}</h2>
        <div className="feature-grid">
          {content.features.list.map((feature, index) => (
            <div key={index} className="feature-card">
              <div className="icon">🚀</div>
              <h3>{feature}</h3>
              <p>{content.features.description}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Pricing Section */}
      <section id="pricing" className="pricing">
        <h2>{content.pricing.title}</h2>
        <p>{content.pricing.subtitle}</p>
        <div className="pricing-grid">
          {plans.map(plan => (
            <div key={plan.id} className="pricing-card">
              <h3>{plan.name}</h3>
              <div className="price">
                <span className="amount">{formatPrice(plan.price)}</span>
                <span className="period">{content.pricing.period}</span>
              </div>
              <ul className="plan-features">
                {plan.features.map((feature, index) => (
                  <li key={index}>{feature}</li>
                ))}
              </ul>
              <button className="plan-button">
                {content.pricing.buttonPrefix} {plan.name}
              </button>
            </div>
          ))}
        </div>
      </section>

      {/* Footer Section */}
      <footer className="footer">
        <div className="footer-content">
          {content.footer.sections.map(section => (
            <div key={section.title} className="footer-column">
              <h4>{section.title}</h4>
              <ul>
                {section.links.map(link => (
                  <li key={link}><a href="#">{link}</a></li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="footer-bottom">
          <p>{content.footer.copyright}</p>
        </div>
      </footer>
    </div>
  );
};
