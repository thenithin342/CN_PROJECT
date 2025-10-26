# CodeRabbit Integration Setup

This project is configured with CodeRabbit for automated code review, testing, and analysis.

## 🚀 Quick Start

### 1. Install CodeRabbit GitHub App

1. Visit [CodeRabbit GitHub App](https://github.com/apps/coderabbitai)
2. Click "Install" and select your repository
3. Grant permissions for:
   - Read access to code and pull requests
   - Write access to comments

### 2. Configure GitHub Secrets

Add the following secrets to your GitHub repository:

**Settings → Secrets and variables → Actions → New repository secret**

- `CODERABBIT_API_KEY`: Get from [CodeRabbit Dashboard](https://coderabbit.ai/dashboard)

### 3. Enable GitHub Actions

The workflow is automatically enabled in `.github/workflows/coderabbit-review.yml`

## 📋 Features Enabled

### Code Review
- ✅ Automated code review on pull requests
- ✅ Security vulnerability detection
- ✅ Performance analysis
- ✅ Best practices suggestions
- ✅ Code smell detection

### Quality Analysis
- ✅ Linting with flake8
- ✅ Type checking with mypy
- ✅ Code formatting with black
- ✅ Security scanning with bandit
- ✅ Dependency vulnerability check

### Component-Specific Reviews

#### Audio System (`client/audio`, `server/audio`)
- Real-time processing optimization
- Memory efficiency checks
- Latency analysis

#### Network Protocol (`common`, `main_client`, `main_server`)
- Security auditing
- Error handling review
- Protocol design validation

#### File Transfer (`client/files`, `server/files`)
- Security analysis
- Reliability checks
- Progress tracking verification

#### Screen Sharing (`client/screen`, `server/screen`)
- Performance optimization
- Bandwidth optimization
- Image compression analysis

## 🎯 Configuration

### Customize Review Settings

Edit `.github/coderabbit.yml` to adjust:

```yaml
reviews:
  review_state: approved  # Change approval behavior
  auto_merge: true        # Enable auto-merge

analyses:
  security:
    severity_threshold: medium  # Set security threshold
    
  test_coverage:
    target_percentage: 70  # Set coverage target
```

## 📊 What CodeRabbit Checks

### Security
- SQL injection vulnerabilities
- Hardcoded credentials
- Unsafe deserialization
- Insecure random number generation
- Missing authentication/authorization

### Performance
- Database query optimization
- Memory leaks
- Inefficient algorithms
- Excessive resource usage

### Best Practices
- Code structure
- Naming conventions
- Comment quality
- Error handling
- Logging practices

## 🔔 Notifications

CodeRabbit will comment on:
- Pull requests with review findings
- Security vulnerabilities
- Performance issues
- Code quality improvements
- Test coverage gaps

## 🛠 Local Testing

Before pushing, you can run checks locally:

```bash
# Install development dependencies
pip install flake8 black mypy bandit pytest

# Run linter
flake8 client/ server/ --max-line-length=127

# Format code
black client/ server/ common/

# Check types
mypy client/ server/ --ignore-missing-imports

# Security scan
bandit -r client/ server/

# Run tests (if you have them)
pytest tests/
```

## 📈 Monitoring

- **Pull Request Reviews**: Automatic reviews on every PR
- **Security Scans**: Weekly automated scans
- **Code Quality Reports**: Available in Actions tab

## 🆘 Troubleshooting

### CodeRabbit not reviewing
1. Check GitHub App is installed
2. Verify workflow is enabled in Actions tab
3. Check `.github/coderabbit.yml` syntax

### Missing reviews
1. Ensure `CODERABBIT_API_KEY` secret is set
2. Check GitHub App permissions
3. Verify branch protection rules allow app

### Integration issues
Check the Actions workflow run logs in the "Actions" tab

## 📚 Resources

- [CodeRabbit Documentation](https://docs.coderabbit.ai)
- [GitHub Actions Docs](https://docs.github.com/en/actions)
- [Python Code Quality Tools](https://realpython.com/python-code-quality/)

## 🎉 Benefits

✅ **Faster Code Review**: Automated feedback in minutes  
✅ **Better Security**: Catch vulnerabilities early  
✅ **Higher Quality**: Consistent code standards  
✅ **Less Technical Debt**: Proactive issue detection  
✅ **Knowledge Sharing**: Learn best practices from AI insights

---

**Happy Coding! 🚀**
