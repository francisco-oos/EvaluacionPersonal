from pathlib import Path


def test_mobile_auth_admin_keyboard_reset_and_department_export_controls_exist():
    root = Path(__file__).resolve().parents[1]
    javascript = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")
    stylesheet = (root / "app" / "static" / "styles.css").read_text(encoding="utf-8")
    html = (root / "app" / "templates" / "index.html").read_text(encoding="utf-8")

    assert "setupKeyboardAwareActions" in javascript
    assert "visualViewport" in javascript
    assert "--keyboard-offset" in stylesheet
    assert "body.keyboard-open .workflow-actions" in stylesheet
    assert "prepareBlankCapture();" in javascript
    assert 'id="loginForm"' in html
    assert 'id="adminView"' in html
    assert 'id="departmentForm"' in html
    assert 'id="positionForm"' in html
    assert 'id="userForm"' in html
    assert 'id="downloadAllExcel"' in html
    assert 'id="downloadDepartmentsZip"' in html
    assert "department_id" in javascript
    assert "status=all" in javascript
